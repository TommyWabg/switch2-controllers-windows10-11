"""A class used to find switch 2 controllers via Bluetooth
"""
import threading
from bleak import BleakScanner, BleakClient, BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak.exc import BleakError
import asyncio
import logging
import bluetooth
import yaml
from utils import to_hex, convert_mac_string_to_value, decodeu
from controller import Controller, ControllerInputData, NINTENDO_VENDOR_ID, CONTROLER_NAMES, VibrationData, NSO_GAMECUBE_CONTROLLER_PID
from virtual_controller import VirtualController
from config import CONFIG

logger = logging.getLogger(__name__)

NINTENDO_BLUETOOTH_MANUFACTURER_ID = 0x0553
VIRTUAL_CONTROLLERS = [None] * 8
UPDATE_CALLBACK = None
DISCOVERER_LOOP = None
DISCONNECT_CALLBACK = None
IS_SHUTTING_DOWN = False

async def run_discovery(update_controllers_threadsafe, quit_event):
    global VIRTUAL_CONTROLLERS, UPDATE_CALLBACK, DISCOVERER_LOOP, DISCONNECT_CALLBACK
    UPDATE_CALLBACK = update_controllers_threadsafe
    DISCOVERER_LOOP = asyncio.get_running_loop()
    
    try:
        host_mac_value = convert_mac_string_to_value(bluetooth.read_local_bdaddr()[0])
        connected_mac_addresses: list[str] = []

        async def disconnected_controller(controller: Controller):
            logger.info(f"Controller disconected {controller.client.address}")
            
            if controller.client.address in connected_mac_addresses:
                connected_mac_addresses.remove(controller.client.address)
                
            for i, vc in enumerate(VIRTUAL_CONTROLLERS[:]):
                if vc is not None and await vc.remove_controller(controller):
                    VIRTUAL_CONTROLLERS[i] = None
            
            if IS_SHUTTING_DOWN:
                return
                
            reorder_controllers()
            
            if UPDATE_CALLBACK is not None:
                UPDATE_CALLBACK(list(VIRTUAL_CONTROLLERS))
            
            await update_all_player_leds()

        DISCONNECT_CALLBACK = disconnected_controller
        lock = asyncio.Lock()

        async def add_controller(device: BLEDevice, paired: bool):
            try:
                controller = await Controller.create_from_device(device)
                logger.info(f"Connected to {device.address}")
                controller.disconnected_callback = disconnected_controller
                if not paired:
                    await controller.pair()
                    logger.info(f"Paired successfully to {device.address}")

                virtual_controller = None
                await lock.acquire()
                try:
                    if CONFIG.combine_joycons and not controller.side_buttons_pressed:
                        if controller.is_joycon_left():
                            virtual_controller = next(filter(lambda vc: vc is not None and vc.is_single_joycon_right(), VIRTUAL_CONTROLLERS), None)
                        elif controller.is_joycon_right():
                            virtual_controller = next(filter(lambda vc: vc is not None and vc.is_single_joycon_left(), VIRTUAL_CONTROLLERS), None)

                    if virtual_controller is None:
                        slot_index = next(i for i, c in enumerate(VIRTUAL_CONTROLLERS) if c == None)
                        virtual_controller = VirtualController(slot_index + 1, disconnected_controller)
                        VIRTUAL_CONTROLLERS[slot_index] = virtual_controller
                    
                    virtual_controller.add_controller(controller)
                finally:
                    lock.release()
                
                await virtual_controller.init_added_controller(controller)
                
                reorder_controllers()
                
                if UPDATE_CALLBACK is not None:
                    UPDATE_CALLBACK(list(VIRTUAL_CONTROLLERS))
                
                await update_all_player_leds()

                logger.info(VIRTUAL_CONTROLLERS)
            except Exception:
                logger.exception(f"Unable to initialize device {device.address}")
                if device.address in connected_mac_addresses:
                    connected_mac_addresses.remove(device.address)
                print("\nConnection failed. Please press a button on the controller or hold SYNC to re-pair.")

        async def callback(device: BLEDevice, advertising_data: AdvertisementData):
            if device.address in connected_mac_addresses:
                return
            nintendo_manufacturer_data = advertising_data.manufacturer_data.get(NINTENDO_BLUETOOTH_MANUFACTURER_ID)
            if nintendo_manufacturer_data:
                vendor_id = decodeu(nintendo_manufacturer_data[3:5])
                product_id = decodeu(nintendo_manufacturer_data[5:7])
                reconnect_mac = decodeu(nintendo_manufacturer_data[10:16])
                if vendor_id == NINTENDO_VENDOR_ID and product_id in CONTROLER_NAMES:
                    logger.debug(f"Manufacturer data: {to_hex(nintendo_manufacturer_data)}")
                    if reconnect_mac == 0:
                        logger.info(f"Found pairing device {CONTROLER_NAMES[product_id]} {device.address}")
                        connected_mac_addresses.append(device.address)
                        await add_controller(device, False)
                    elif reconnect_mac == host_mac_value:
                        logger.info(f"Found already paired device {CONTROLER_NAMES[product_id]} {device.address}")
                        connected_mac_addresses.append(device.address)
                        await add_controller(device, True)

        async with BleakScanner(callback) as scanner:
            print("Presss a button on a paired controller, or hold sync button on an unpaired controller")
            await asyncio.get_event_loop().run_in_executor(None, quit_event.wait)
    finally:
        for vc in VIRTUAL_CONTROLLERS:
            if vc is not None:
                for controller in vc.controllers:
                    await controller.disconnect()

def start_discoverer(update_controllers_threadsafe, quit_event):
    asyncio.run(run_discovery(update_controllers_threadsafe, quit_event))

def reorder_controllers():
    global VIRTUAL_CONTROLLERS
    active_vcs = []
    for vc in VIRTUAL_CONTROLLERS:
        if vc is not None:
            active_vcs.append(vc)
    
    if not active_vcs:
        return

    # Priority: Pro Controller > GameCube > Combined Joycon > Left Joycon > Right Joycon
    def get_priority(vc):
        if vc.is_single():
            c = vc.controllers[0]
            if c.is_pro_controller(): return 0
            if c.controller_info.product_id == NSO_GAMECUBE_CONTROLLER_PID: return 1
            if c.is_joycon_left(): return 3
            if c.is_joycon_right(): return 4
        else:
            # Combined Joycon pair
            return 2
        return 5

    active_vcs.sort(key=get_priority)
    
    new_list = [None] * 8
    for i, vc in enumerate(active_vcs):
        new_list[i] = vc
        vc.player_number = i + 1
    
    VIRTUAL_CONTROLLERS[:] = new_list

def set_shutting_down(val):
    global IS_SHUTTING_DOWN
    IS_SHUTTING_DOWN = val

async def update_all_player_leds():
    for vc in VIRTUAL_CONTROLLERS:
        if vc is not None:
            for c in vc.controllers:
                await c.set_leds(vc.player_number)

async def _split_controller_async(vc_index):
    vc = VIRTUAL_CONTROLLERS[vc_index]
    if vc is not None and not vc.is_single():
        c2 = vc.controllers.pop()
        await vc.init_added_controller(vc.controllers[0]) # reinit first
        
        slot_index = next(i for i, c in enumerate(VIRTUAL_CONTROLLERS) if c == None)
        new_vc = VirtualController(slot_index + 1, DISCONNECT_CALLBACK)
        new_vc.add_controller(c2)
        VIRTUAL_CONTROLLERS[slot_index] = new_vc
        await new_vc.init_added_controller(c2)
        
        reorder_controllers()

        if UPDATE_CALLBACK is not None:
            UPDATE_CALLBACK(list(VIRTUAL_CONTROLLERS))
            
        await update_all_player_leds()

def split_controller(vc_index):
    if DISCOVERER_LOOP and DISCOVERER_LOOP.is_running():
        asyncio.run_coroutine_threadsafe(_split_controller_async(vc_index), DISCOVERER_LOOP)

async def _merge_controllers_async(vc_index1, vc_index2):
    # Ensure vc_index1 is the lower index to prioritize Player 1
    if vc_index1 > vc_index2:
        vc_index1, vc_index2 = vc_index2, vc_index1
        
    vc1 = VIRTUAL_CONTROLLERS[vc_index1]
    vc2 = VIRTUAL_CONTROLLERS[vc_index2]
    
    if vc1 is not None and vc2 is not None and vc1.is_single() and vc2.is_single():
        c2 = vc2.controllers[0]
        await vc2.remove_controller(c2)
        VIRTUAL_CONTROLLERS[vc_index2] = None
        
        vc1.add_controller(c2)
        await vc1.init_added_controller(c2)
        
        reorder_controllers()

        if UPDATE_CALLBACK is not None:
            UPDATE_CALLBACK(list(VIRTUAL_CONTROLLERS))
            
        await update_all_player_leds()

def merge_controllers(vc_index1, vc_index2):
    if DISCOVERER_LOOP and DISCOVERER_LOOP.is_running():
        asyncio.run_coroutine_threadsafe(_merge_controllers_async(vc_index1, vc_index2), DISCOVERER_LOOP)

if __name__ == "__main__":
    start_discoverer(None, threading.Event())