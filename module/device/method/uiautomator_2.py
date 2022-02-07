from json.decoder import JSONDecodeError

import uiautomator2 as u2
from adbutils.errors import AdbError
from lxml import etree

from module.base.decorator import cached_property
from module.base.utils import *
from module.device.connection import Connection
from module.device.method.utils import possible_reasons, handle_adb_error, RETRY_TRIES, RETRY_DELAY
from module.exception import RequestHumanTakeover
from module.logger import logger


def retry(func):
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (Uiautomator2):
        """
        for _ in range(RETRY_TRIES):
            try:
                return func(self, *args, **kwargs)
            except RequestHumanTakeover:
                # Can't handle
                break
            except ConnectionResetError as e:
                # When adb server was killed
                logger.error(e)
                self.adb_connect(self.serial)
            except JSONDecodeError as e:
                # device.set_new_command_timeout(604800)
                # json.decoder.JSONDecodeError: Expecting value: line 1 column 2 (char 1)
                logger.error(e)
                self.install_uiautomator2()
            except AdbError as e:
                if not handle_adb_error(e):
                    break
            except RuntimeError as e:
                # RuntimeError: USB device 127.0.0.1:5555 is offline
                if not handle_adb_error(e):
                    break
            except AssertionError as e:
                # assert c.read string(4) == _OKAY
                logger.exception(e)
                possible_reasons(
                    'If you are using BlueStacks or LD player, '
                    'please enable ADB in the settings of your emulator'
                )
                break
            except Exception as e:
                # Unknown
                # Probably trucked image
                logger.exception(e)

            self.sleep(RETRY_DELAY)

        logger.critical(f'Retry {func.__name__}() failed')
        raise RequestHumanTakeover

    return retry_wrapper


class Uiautomator2(Connection):
    @cached_property
    def u2(self) -> u2.Device:
        device = u2.connect(self.serial)
        device.set_new_command_timeout(604800)
        return device

    @retry
    def screenshot_uiautomator2(self):
        image = self.u2.screenshot(format='raw')
        image = np.fromstring(image, np.uint8)
        image = cv2.imdecode(image, cv2.IMREAD_COLOR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        return image

    @retry
    def click_uiautomator2(self, x, y):
        self.u2.click(x, y)

    @retry
    def long_click_uiautomator2(self, x, y, duration=(1, 1.2)):
        self.u2.long_click(x, y, duration=duration)

    @retry
    def swipe_uiautomator2(self, p1, p2, duration=0.1):
        self.u2.swipe(*p1, *p2, duration=duration)

    @retry
    def _drag_along(self, path):
        """Swipe following path.

        Args:
            path (list): (x, y, sleep)

        Examples:
            al.drag_along([
                (403, 421, 0.2),
                (821, 326, 0.1),
                (821, 326-10, 0.1),
                (821, 326+10, 0.1),
                (821, 326, 0),
            ])
            Equals to:
            al.device.touch.down(403, 421)
            time.sleep(0.2)
            al.device.touch.move(821, 326)
            time.sleep(0.1)
            al.device.touch.move(821, 326-10)
            time.sleep(0.1)
            al.device.touch.move(821, 326+10)
            time.sleep(0.1)
            al.device.touch.up(821, 326)
        """
        length = len(path)
        for index, data in enumerate(path):
            x, y, second = data
            if index == 0:
                self.u2.touch.down(x, y)
                logger.info(point2str(x, y) + ' down')
            elif index - length == -1:
                self.u2.touch.up(x, y)
                logger.info(point2str(x, y) + ' up')
            else:
                self.u2.touch.move(x, y)
                logger.info(point2str(x, y) + ' move')
            self.sleep(second)

    def drag_uiautomator2(self, p1, p2, segments=1, shake=(0, 15), point_random=(-10, -10, 10, 10),
                          shake_random=(-5, -5, 5, 5), swipe_duration=0.25, shake_duration=0.1):
        """Drag and shake, like:
                     /\
        +-----------+  +  +
                        \/
        A simple swipe or drag don't work well, because it only has two points.
        Add some way point to make it more like swipe.

        Args:
            p1 (tuple): Start point, (x, y).
            p2 (tuple): End point, (x, y).
            segments (int):
            shake (tuple): Shake after arrive end point.
            point_random: Add random to start point and end point.
            shake_random: Add random to shake array.
            swipe_duration: Duration between way points.
            shake_duration: Duration between shake points.
        """
        p1 = np.array(p1) - random_rectangle_point(point_random)
        p2 = np.array(p2) - random_rectangle_point(point_random)
        path = [(x, y, swipe_duration) for x, y in random_line_segments(p1, p2, n=segments, random_range=point_random)]
        path += [
            (*p2 + shake + random_rectangle_point(shake_random), shake_duration),
            (*p2 - shake - random_rectangle_point(shake_random), shake_duration),
            (*p2, shake_duration)
        ]
        path = [(int(x), int(y), d) for x, y, d in path]
        self._drag_along(path)

    @retry
    def app_current_uiautomator2(self):
        """
        Returns:
            str: Package name.
        """
        result = self.u2.app_current()
        return result['package']

    @retry
    def app_start_uiautomator2(self, package_name):
        try:
            self.u2.app_start(package_name)
        except u2.exceptions.BaseError as e:
            # BaseError: package "com.bilibili.azurlane" not found
            logger.error(e)
            possible_reasons(f'"{package_name}" not found, please check setting Emulator.PackageName')
            raise RequestHumanTakeover

    @retry
    def app_stop_uiautomator2(self, package_name):
        self.u2.app_stop(package_name)

    @retry
    def dump_hierarchy_uiautomator2(self) -> etree._Element:
        content = self.u2.dump_hierarchy(compressed=True)
        hierarchy = etree.fromstring(content.encode('utf-8'))
        return hierarchy