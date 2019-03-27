
import os
import time
from itertools import cycle
import argparse
import evdev
from evdev import ecodes
import yaml

class BluetoothDevice:
    device = None

    def get_input_device(self, path):
        return evdev.InputDevice(path)

    def find_input_device(self, search_term):
        """
        Return the input device if there is only one that matches the search term.
        """
        all_devices = [evdev.InputDevice(path) for path in evdev.list_devices()]
        likely_devices = []
        for device in all_devices:
            if search_term.lower() in device.name.lower():
                likely_devices.append(device)

        if len(likely_devices) == 1:
            # correct device was likely found
            return likely_devices[0]

        if len(likely_devices) >= 2:
            raise ValueError("Found multiple device possible devices. Please specify the specific event_input_path.")

    def load_device(self, search_term):
        """
        Try to load the device until one that matches the search term exists.
        """
        device = None
        while device is None:
            device = self.find_input_device(search_term)
            if device is None:
                print("Device matching '{}' couldn't be found. Trying again in 3 seconds.".format(search_term))
                time.sleep(3)
        self.device = device


class BluetoothGameController(BluetoothDevice):
    """
    Generator of cordinates of a bouncing moving square for simulations.
    """

    def __init__(self, event_input_device=None, config_path=None, device_search_term=None, verbose=False):


        self.verbose = verbose
        self.running = False

        self.state = {}
        self.angle = 0.0
        self.throttle = 0.0

        self.throttle_scale = 1.0
        self.throttle_scale_increment = .05
        self.y_axis_direction = -1  # pushing stick forward gives negative values

        self.drive_mode_toggle = cycle(['user', 'local_angle', 'local'])
        self.drive_mode = next(self.drive_mode_toggle)

        self.recording_toggle = cycle([True, False])
        self.recording = next(self.recording_toggle)

        if config_path is None:
            config_path = self._get_default_config_path()
        self.config = self._load_config(config_path)

        self.btn_map = self.config.get('button_map')
        self.joystick_max_value = self.config.get('joystick_max_value', 1280)

        # search term used to find the event stream input (/dev/input/...)
        self.device_search_term = device_search_term or self.config.get('device_search_term', 1280)

        if event_input_device is None:
            self.load_device(self.device_search_term)
            print(self.device)
        else:
            self.device = event_input_device

        self.func_map = {
            'LEFT_STICK_X': self.update_angle,
            'LEFT_STICK_Y': self.update_throttle,
            'B': self.toggle_recording,
            'A': self.toggle_drive_mode,
            'PAD_UP': self.increment_throttle_scale,
            'PAD_DOWN': self.decrement_throttle_scale,
        }

    def _get_default_config_path(self):
        return os.path.join(os.path.dirname(__file__), 'wiiu_config.yml')

    def _load_config(self, config_path):
        with open(config_path, 'r') as f:
            config = yaml.load(f)
        return config

    def read_loop(self):
        """
        Read input, map events to button names and scale joystic values to between 1 and 0.
        """
        try:
            event = next(self.device.read_loop())
            btn = self.btn_map.get(event.code)
            val = event.value
            if event.type == ecodes.EV_ABS:
                val = val / float(self.joystick_max_value)
            return btn, val
        except OSError as e:
            print('OSError: Likely lost connection with controller. Trying to reconnect now. Error: {}'.format(e))
            time.sleep(.1)
            self.load_device(self.device_search_term)
            return None, None


    def update_state_from_loop(self):
        btn, val = self.read_loop()

        # update state
        self.state[btn] = val

        # run_functions
        func = self.func_map.get(btn)
        if func is not None:
            func(val)

        if self.verbose == True:
            print("button: {}, value:{}".format(btn, val))

    def update(self):
        while True:
            self.update_state_from_loop()

    def run(self):
        self.update_state_from_loop()
        return self.angle, self.throttle, self.drive_mode, self.recording

    def run_threaded(self, img_arr=None):
        return self.angle, self.throttle, self.drive_mode, self.recording

    def shutdown(self):
        self.running = False
        time.sleep(0.1)

    def profile(self):
        msg = """
        Starting to measure the events per second. Move both joysticks around as fast as you can. 
        Every 1000 events you'll see how many events are being recieved per second. After 10,000 records
        you'll see a score for the controller. 
        """
        print(msg)
        event_total = 0
        start_time = time.time()
        results = []
        while True:
            self.read_loop()
            event_total += 1
            if event_total > 1000:
                end_time = time.time()
                seconds_elapsed = end_time - start_time
                events_per_second = event_total / seconds_elapsed
                results.append(events_per_second)
                print('events per seconds: {}'.format(events_per_second))
                start_time = time.time()
                event_total = 0
                if len(results) > 9:
                    break

        sorted_results = sorted(results)
        best_5_results = sorted_results[5:]
        max = best_5_results[-1]
        average = sum(best_5_results) / len(best_5_results)

        print('RESULTS:')
        print('Events per second. MAX: {}, AVERAGE: {}'.format(max, average))



    def update_angle(self, val):
        self.angle = val
        return

    def update_throttle(self, val):
        self.throttle = val * self.throttle_scale * self.y_axis_direction
        return

    def toggle_recording(self, val):
        if val == 1:
            self.recording = next(self.recording_toggle)
        return

    def toggle_drive_mode(self, val):
        if val == 1:
            self.drive_mode = next(self.drive_mode_toggle)
        return

    def increment_throttle_scale(self, val):
        if val == 1:
            self.throttle_scale += self.throttle_scale_increment
        return

    def decrement_throttle_scale(self, val):
        if val == 1:
            self.throttle_scale -= self.throttle_scale_increment
        return


if __name__ == "__main__":
    device_search_term = input("""Please give a string that can identify the bluetooth device (ie. nintendo)""")
    if device_search_term == "":
        print('No search term given. Using Nintendo.')
        device_search_term = "Nintendo"

    parser = argparse.ArgumentParser(description='Scripts to help test and setup your controller.')
    parser.add_argument('command', metavar='command', type=str, help='log or profile')

    args = parser.parse_args()
    print(args.command)
    if args.command == 'profile':
        ctl = BluetoothGameController(device_search_term=device_search_term)
        ctl.profile()
    elif args.command == 'log':
        ctl = BluetoothGameController(verbose=True, device_search_term=device_search_term)
        ctl.update()
