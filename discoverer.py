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
from controller import Controller, ControllerInputData, NINTENDO_VENDOR_ID, CONTROLER_NAMES, VibrationData
from virtual_controller import VirtualController
from config import CONFIG

logger = logging.getLogger(__name__)

NINTENDO_BLUETOOTH_MANUFACTURER_ID = 0x0553

async def run_discovery(update_controllers_threadsafe, quit_event):
    try:
        host_mac_value = convert_mac_string_to_value(bluetooth.read_local_bdaddr()[0])
        connected_mac_addresses: list[str] = []
        virtual_controllers: list[VirtualController] = [None] * 8

        async def disconnected_controller(controller: Controller):
            logger.info(f"Controller disconected {controller.client.address}")
            
            if controller.client.address in connected_mac_addresses:
                connected_mac_addresses.remove(controller.client.address)
                
            for i, vc in enumerate(virtual_controllers[:]):
                if vc is not None and await vc.remove_controller(controller):
                    virtual_controllers[i] = None
                    
            logger.info(virtual_controllers)
            if update_controllers_threadsafe is not None:
                update_controllers_threadsafe(list(virtual_controllers))

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
                            virtual_controller = next(filter(lambda vc: vc is not None and vc.is_single_joycon_right(), virtual_controllers), None)
                        elif controller.is_joycon_right():
                            virtual_controller = next(filter(lambda vc: vc is not None and vc.is_single_joycon_left(), virtual_controllers), None)

                    if virtual_controller is None:
                        slot_index = next(i for i, c in enumerate(virtual_controllers) if c == None)
                        virtual_controller = VirtualController(slot_index + 1, disconnected_controller)
                        virtual_controllers[slot_index] = virtual_controller
                    
                    virtual_controller.add_controller(controller)
                finally:
                    lock.release()
                
                await virtual_controller.init_added_controller(controller)

                logger.info(virtual_controllers)
                if update_controllers_threadsafe is not None:
                    update_controllers_threadsafe(list(virtual_controllers))
            except Exception:
                logger.exception(f"Unable to initialize device {device.address}")
                connected_mac_addresses.remove(device.address)

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
        for vc in virtual_controllers:
            if vc is not None:
                for controller in vc.controllers:
                    await controller.disconnect()

def start_discoverer(update_controllers_threadsafe, quit_event):
    asyncio.run(run_discovery(update_controllers_threadsafe, quit_event))

if __name__ == "__main__":
    start_discoverer(None, threading.Event())
