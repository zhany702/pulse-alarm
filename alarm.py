from __future__ import (
    unicode_literals,
    print_function,
    absolute_import,
    division
)
str = type('')

import virtual_gpiozero
from virtual_gpiozero.pins.mock import MockFactory
virtual_gpiozero.Device.pin_factory = MockFactory()


import sys, time, os
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from PyQt5 import QtCore, QtGui, QtWidgets
from guiScript import Ui_MainWindow
from PyQt5.QtGui import *
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from virtual_gpiozero import *



from threading import Lock
from itertools import repeat, cycle, chain
from colorzero import Color
from collections import OrderedDict
try:
    from math import log2
except ImportError:
    from .compat import log2
import warnings

from virtual_gpiozero.exc import OutputDeviceBadValue, GPIOPinMissing, PWMSoftwareFallback
from virtual_gpiozero.devices import GPIODevice, Device, CompositeDevice
##from virtual_gpiozero.mixins import SourceMixin
from virtual_gpiozero.threads import GPIOThread
from virtual_gpiozero.tones import Tone
try:
    from virtual_gpiozero.pins.pigpio import PiGPIOFactory
except ImportError:
    PiGPIOFactory = None

import inspect
import weakref
from functools import wraps, partial
from threading import Event
from collections import deque
try:
    from statistics import median
except ImportError:
    from .compat import median
import warnings

from virtual_gpiozero.threads import GPIOThread
from virtual_gpiozero.exc import (
    BadEventHandler,
    BadWaitTime,
    BadQueueLen,
    DeviceClosed,
    CallbackSetToNone,
    )

import warnings
#from time import sleep, time
from threading import Event, Lock
try:
    from statistics import median
except ImportError:
    from .compat import median

from virtual_gpiozero.exc import InputDeviceError, DeviceClosed, DistanceSensorNoEcho, \
    PinInvalidState, PWMSoftwareFallback
from virtual_gpiozero.devices import GPIODevice
from virtual_gpiozero.mixins import GPIOQueue, EventsMixin, HoldMixin

try:
    from virtual_gpiozero.pins.pigpio import PiGPIOFactory
except ImportError:
    PiGPIOFactory = None

callback_warning = (
    'The callback was set to None. This may have been unintentional '
    'e.g. btn.when_pressed = pressed() instead of btn.when_pressed = pressed'
)

class ValuesMixin(object):
    """
    Adds a :attr:`values` property to the class which returns an infinite
    generator of readings from the :attr:`~Device.value` property. There is
    rarely a need to use this mixin directly as all base classes in GPIO Zero
    include it.

    .. note::

        Use this mixin *first* in the parent class list.
    """

    @property
    def values(self):
        """
        An infinite iterator of values read from :attr:`value`.
        """
        while True:
            try:
                yield self.value
            except DeviceClosed:
                break


class SourceMixin(object):
    """
    Adds a :attr:`source` property to the class which, given an iterable or a
    :class:`ValuesMixin` descendent, sets :attr:`~Device.value` to each member
    of that iterable until it is exhausted. This mixin is generally included in
    novel output devices to allow their state to be driven from another device.

    .. note::

        Use this mixin *first* in the parent class list.
    """

    def __init__(self, *args, **kwargs):
        self._source = None
        self._source_thread = None
        self._source_delay = 0.01
        super(SourceMixin, self).__init__(*args, **kwargs)

    def close(self):
        self.source = None
        super(SourceMixin, self).close()

    def _copy_values(self, source):
        for v in source:
            self.value = v
            if self._source_thread.stopping.wait(self._source_delay):
                break

    @property
    def source_delay(self):
        """
        The delay (measured in seconds) in the loop used to read values from
        :attr:`source`. Defaults to 0.01 seconds which is generally sufficient
        to keep CPU usage to a minimum while providing adequate responsiveness.
        """
        return self._source_delay

    @source_delay.setter
    def source_delay(self, value):
        if value < 0:
            raise BadWaitTime('source_delay must be 0 or greater')
        self._source_delay = float(value)

    @property
    def source(self):
        """
        The iterable to use as a source of values for :attr:`value`.
        """
        return self._source

    @source.setter
    def source(self, value):
        if getattr(self, '_source_thread', None):
            self._source_thread.stop()
        self._source_thread = None
        if isinstance(value, ValuesMixin):
            value = value.values
        self._source = value
        if value is not None:
            self._source_thread = GPIOThread(target=self._copy_values, args=(value,))
            self._source_thread.start()

class EventsMixin(object):
    """
    Adds edge-detected :meth:`when_activated` and :meth:`when_deactivated`
    events to a device based on changes to the :attr:`~Device.is_active`
    property common to all devices. Also adds :meth:`wait_for_active` and
    :meth:`wait_for_inactive` methods for level-waiting.

    .. note::

        Note that this mixin provides no means of actually firing its events;
        call :meth:`_fire_events` in sub-classes when device state changes to
        trigger the events. This should also be called once at the end of
        initialization to set initial states.
    """
    def __init__(self, *args, **kwargs):
        super(EventsMixin, self).__init__(*args, **kwargs)
        self._active_event = Event()
        self._inactive_event = Event()
        self._when_activated = None
        self._when_deactivated = None
        self._last_active = None
        self._last_changed = self.pin_factory.ticks()

    def wait_for_active(self, timeout=None):
        """
        Pause the script until the device is activated, or the timeout is
        reached.

        :type timeout: float or None
        :param timeout:
            Number of seconds to wait before proceeding. If this is
            :data:`None` (the default), then wait indefinitely until the device
            is active.
        """
        return self._active_event.wait(timeout)

    def wait_for_inactive(self, timeout=None):
        """
        Pause the script until the device is deactivated, or the timeout is
        reached.

        :type timeout: float or None
        :param timeout:
            Number of seconds to wait before proceeding. If this is
            :data:`None` (the default), then wait indefinitely until the device
            is inactive.
        """
        return self._inactive_event.wait(timeout)

    @property
    def when_activated(self):
        """
        The function to run when the device changes state from inactive to
        active.

        This can be set to a function which accepts no (mandatory) parameters,
        or a Python function which accepts a single mandatory parameter (with
        as many optional parameters as you like). If the function accepts a
        single mandatory parameter, the device that activated will be passed
        as that parameter.

        Set this property to :data:`None` (the default) to disable the event.
        """
        return self._when_activated

    @when_activated.setter
    def when_activated(self, value):
        if self.when_activated is None and value is None:
            warnings.warn(CallbackSetToNone(callback_warning))
        self._when_activated = self._wrap_callback(value)

    @property
    def when_deactivated(self):
        """
        The function to run when the device changes state from active to
        inactive.

        This can be set to a function which accepts no (mandatory) parameters,
        or a Python function which accepts a single mandatory parameter (with
        as many optional parameters as you like). If the function accepts a
        single mandatory parameter, the device that deactivated will be
        passed as that parameter.

        Set this property to :data:`None` (the default) to disable the event.
        """
        return self._when_deactivated

    @when_deactivated.setter
    def when_deactivated(self, value):
        if self.when_deactivated is None and value is None:
            warnings.warn(CallbackSetToNone(callback_warning))
        self._when_deactivated = self._wrap_callback(value)

    @property
    def active_time(self):
        """
        The length of time (in seconds) that the device has been active for.
        When the device is inactive, this is :data:`None`.
        """
        if self._active_event.is_set():
            return self.pin_factory.ticks_diff(self.pin_factory.ticks(),
                                               self._last_changed)
        else:
            return None

    @property
    def inactive_time(self):
        """
        The length of time (in seconds) that the device has been inactive for.
        When the device is active, this is :data:`None`.
        """
        if self._inactive_event.is_set():
            return self.pin_factory.ticks_diff(self.pin_factory.ticks(),
                                               self._last_changed)
        else:
            return None

    def _wrap_callback(self, fn):
        if fn is None:
            return None
        elif not callable(fn):
            raise BadEventHandler('value must be None or a callable')
        # If fn is wrapped with partial (i.e. partial, partialmethod, or wraps
        # has been used to produce it) we need to dig out the "real" function
        # that's been wrapped along with all the mandatory positional args
        # used in the wrapper so we can test the binding
        args = ()
        wrapped_fn = fn
        while isinstance(wrapped_fn, partial):
            args = wrapped_fn.args + args
            wrapped_fn = wrapped_fn.func
        if inspect.isbuiltin(wrapped_fn):
            # We can't introspect the prototype of builtins. In this case we
            # assume that the builtin has no (mandatory) parameters; this is
            # the most reasonable assumption on the basis that pre-existing
            # builtins have no knowledge of gpiozero, and the sole parameter
            # we would pass is a gpiozero object
            return fn
        else:
            # Try binding ourselves to the argspec of the provided callable.
            # If this works, assume the function is capable of accepting no
            # parameters
            try:
                inspect.getcallargs(wrapped_fn, *args)
                return fn
            except TypeError:
                try:
                    # If the above fails, try binding with a single parameter
                    # (ourselves). If this works, wrap the specified callback
                    inspect.getcallargs(wrapped_fn, *(args + (self,)))
                    @wraps(fn)
                    def wrapper():
                        return fn(self)
                    return wrapper
                except TypeError:
                    raise BadEventHandler(
                        'value must be a callable which accepts up to one '
                        'mandatory parameter')

    def _fire_activated(self):
        # These methods are largely here to be overridden by descendents
        if self.when_activated:
            self.when_activated()

    def _fire_deactivated(self):
        # These methods are largely here to be overridden by descendents
        if self.when_deactivated:
            self.when_deactivated()

    def _fire_events(self, ticks, new_active):
        # NOTE: in contrast to the pin when_changed event, this method takes
        # ticks and *is_active* (i.e. the device's .is_active) as opposed to a
        # pin's *state*.
        old_active, self._last_active = self._last_active, new_active
        if old_active is None:
            # Initial "indeterminate" state; set events but don't fire
            # callbacks as there's not necessarily an edge
            if new_active:
                self._active_event.set()
            else:
                self._inactive_event.set()
        elif old_active != new_active:
            self._last_changed = ticks
            if new_active:
                self._inactive_event.clear()
                self._active_event.set()
                self._fire_activated()
            else:
                self._active_event.clear()
                self._inactive_event.set()
                self._fire_deactivated()


class HoldMixin(EventsMixin):
    """
    Extends :class:`EventsMixin` to add the :attr:`when_held` event and the
    machinery to fire that event repeatedly (when :attr:`hold_repeat` is
    :data:`True`) at internals defined by :attr:`hold_time`.
    """
    def __init__(self, *args, **kwargs):
        self._hold_thread = None
        super(HoldMixin, self).__init__(*args, **kwargs)
        self._when_held = None
        self._held_from = None
        self._hold_time = 1
        self._hold_repeat = False
        self._hold_thread = HoldThread(self)

    def close(self):
        if self._hold_thread is not None:
            self._hold_thread.stop()
        self._hold_thread = None
        super(HoldMixin, self).close()

    def _fire_activated(self):
        super(HoldMixin, self)._fire_activated()
        self._hold_thread.holding.set()

    def _fire_deactivated(self):
        self._held_from = None
        super(HoldMixin, self)._fire_deactivated()

    def _fire_held(self):
        if self.when_held:
            self.when_held()

    @property
    def when_held(self):
        """
        The function to run when the device has remained active for
        :attr:`hold_time` seconds.

        This can be set to a function which accepts no (mandatory) parameters,
        or a Python function which accepts a single mandatory parameter (with
        as many optional parameters as you like). If the function accepts a
        single mandatory parameter, the device that activated will be passed
        as that parameter.

        Set this property to :data:`None` (the default) to disable the event.
        """
        return self._when_held

    @when_held.setter
    def when_held(self, value):
        self._when_held = self._wrap_callback(value)

    @property
    def hold_time(self):
        """
        The length of time (in seconds) to wait after the device is activated,
        until executing the :attr:`when_held` handler. If :attr:`hold_repeat`
        is True, this is also the length of time between invocations of
        :attr:`when_held`.
        """
        return self._hold_time

    @hold_time.setter
    def hold_time(self, value):
        if value < 0:
            raise BadWaitTime('hold_time must be 0 or greater')
        self._hold_time = float(value)

    @property
    def hold_repeat(self):
        """
        If :data:`True`, :attr:`when_held` will be executed repeatedly with
        :attr:`hold_time` seconds between each invocation.
        """
        return self._hold_repeat

    @hold_repeat.setter
    def hold_repeat(self, value):
        self._hold_repeat = bool(value)

    @property
    def is_held(self):
        """
        When :data:`True`, the device has been active for at least
        :attr:`hold_time` seconds.
        """
        return self._held_from is not None

    @property
    def held_time(self):
        """
        The length of time (in seconds) that the device has been held for.
        This is counted from the first execution of the :attr:`when_held` event
        rather than when the device activated, in contrast to
        :attr:`~EventsMixin.active_time`. If the device is not currently held,
        this is :data:`None`.
        """
        if self._held_from is not None:
            return self.pin_factory.ticks_diff(self.pin_factory.ticks(),
                                               self._held_from)
        else:
            return None


class HoldThread(GPIOThread):
    """
    Extends :class:`GPIOThread`. Provides a background thread that repeatedly
    fires the :attr:`HoldMixin.when_held` event as long as the owning
    device is active.
    """
    def __init__(self, parent):
        super(HoldThread, self).__init__(
            target=self.held, args=(weakref.proxy(parent),))
        self.holding = Event()
        self.start()

    def held(self, parent):
        try:
            while not self.stopping.is_set():
                if self.holding.wait(0.1):
                    self.holding.clear()
                    while not (
                            self.stopping.is_set() or
                            parent._inactive_event.wait(parent.hold_time)
                            ):
                        if parent._held_from is None:
                            parent._held_from = parent.pin_factory.ticks()
                        parent._fire_held()
                        if not parent.hold_repeat:
                            break
        except ReferenceError:
            # Parent is dead; time to die!
            pass


class GPIOQueue(GPIOThread):
    """
    Extends :class:`GPIOThread`. Provides a background thread that monitors a
    device's values and provides a running *average* (defaults to median) of
    those values. If the *parent* device includes the :class:`EventsMixin` in
    its ancestry, the thread automatically calls
    :meth:`~EventsMixin._fire_events`.
    """
    def __init__(
            self, parent, queue_len=5, sample_wait=0.0, partial=False,
            average=median, ignore=None):
        assert callable(average)
        super(GPIOQueue, self).__init__(target=self.fill)
        if queue_len < 1:
            raise BadQueueLen('queue_len must be at least one')
        if sample_wait < 0:
            raise BadWaitTime('sample_wait must be 0 or greater')
        if ignore is None:
            ignore = set()
        self.queue = deque(maxlen=queue_len)
        self.partial = bool(partial)
        self.sample_wait = float(sample_wait)
        self.full = Event()
        self.parent = weakref.proxy(parent)
        self.average = average
        self.ignore = ignore

    @property
    def value(self):
        if not self.partial:
            self.full.wait()
        try:
            return self.average(self.queue)
        except (ZeroDivisionError, ValueError):
            # No data == inactive value
            return 0.0

    def fill(self):
        try:
            while not self.stopping.wait(self.sample_wait):
                value = self.parent._read()
                if value not in self.ignore:
                    self.queue.append(value)
                if not self.full.is_set() and len(self.queue) >= self.queue.maxlen:
                    self.full.set()
                if (self.partial or self.full.is_set()) and isinstance(self.parent, EventsMixin):
                    self.parent._fire_events(self.parent.pin_factory.ticks(), self.parent.is_active)
        except ReferenceError:
            # Parent is dead; time to die!
            pass

class InputDevice(GPIODevice):
    """
    Represents a generic GPIO input device.

    This class extends :class:`GPIODevice` to add facilities common to GPIO
    input devices.  The constructor adds the optional *pull_up* parameter to
    specify how the pin should be pulled by the internal resistors. The
    :attr:`is_active` property is adjusted accordingly so that :data:`True`
    still means active regardless of the *pull_up* setting.

    :type pin: int or str
    :param pin:
        The GPIO pin that the device is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :type pull_up: bool or None
    :param pull_up:
        If :data:`True`, the pin will be pulled high with an internal resistor.
        If :data:`False` (the default), the pin will be pulled low.  If
        :data:`None`, the pin will be floating. As gpiozero cannot
        automatically guess the active state when not pulling the pin, the
        *active_state* parameter must be passed.

    :type active_state: bool or None
    :param active_state:
        If :data:`True`, when the hardware pin state is ``HIGH``, the software
        pin is ``HIGH``. If :data:`False`, the input polarity is reversed: when
        the hardware pin state is ``HIGH``, the software pin state is ``LOW``.
        Use this parameter to set the active state of the underlying pin when
        configuring it as not pulled (when *pull_up* is :data:`None`). When
        *pull_up* is :data:`True` or :data:`False`, the active state is
        automatically set to the proper value.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(self, pin=None, pull_up=False, active_state=None,
                 pin_factory=None):
        super(InputDevice, self).__init__(pin, pin_factory=pin_factory)
        try:
            self.pin.function = 'input'
            pull = {None: 'floating', True: 'up', False: 'down'}[pull_up]
            if self.pin.pull != pull:
                self.pin.pull = pull
        except:
            self.close()
            raise

        if pull_up is None:
            if active_state is None:
                raise PinInvalidState(
                    'Pin %d is defined as floating, but "active_state" is not '
                    'defined' % self.pin.number)
            self._active_state = bool(active_state)
        else:
            if active_state is not None:
                raise PinInvalidState(
                    'Pin %d is not floating, but "active_state" is not None' %
                    self.pin.number)
            self._active_state = False if pull_up else True
        self._inactive_state = not self._active_state

    @property
    def pull_up(self):
        """
        If :data:`True`, the device uses a pull-up resistor to set the GPIO pin
        "high" by default.
        """
        pull = self.pin.pull
        if pull == 'floating':
            return None
        else:
            return pull == 'up'

    def __repr__(self):
        try:
            return "<gpiozero.%s object on pin %r, pull_up=%s, is_active=%s>" % (
                self.__class__.__name__, self.pin, self.pull_up, self.is_active)
        except:
            return super(InputDevice, self).__repr__()


class DigitalInputDevice(EventsMixin, InputDevice):
    """
    Represents a generic input device with typical on/off behaviour.

    This class extends :class:`InputDevice` with machinery to fire the active
    and inactive events for devices that operate in a typical digital manner:
    straight forward on / off states with (reasonably) clean transitions
    between the two.

    :type pin: int or str
    :param pin:
        The GPIO pin that the device is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :type pull_up: bool or None
    :param pull_up:
        See descrpition under :class:`InputDevice` for more information.

    :type active_state: bool or None
    :param active_state:
        See description under :class:`InputDevice` for more information.

    :type bounce_time: float or None
    :param bounce_time:
        Specifies the length of time (in seconds) that the component will
        ignore changes in state after an initial change. This defaults to
        :data:`None` which indicates that no bounce compensation will be
        performed.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(
            self, pin=None, pull_up=False, active_state=None, bounce_time=None,
            pin_factory=None):
        super(DigitalInputDevice, self).__init__(
            pin, pull_up=pull_up, active_state=active_state,
            pin_factory=pin_factory)
        try:
            self.pin.bounce = bounce_time
            self.pin.edges = 'both'
            self.pin.when_changed = self._pin_changed
            # Call _fire_events once to set initial state of events
            self._fire_events(self.pin_factory.ticks(), self.is_active)
        except:
            self.close()
            raise

    def _pin_changed(self, ticks, state):
        # XXX This is a bit of a hack; _fire_events takes *is_active* rather
        # than *value*. Here we're assuming no-one's overridden the default
        # implementation of *is_active*.

        #print("GOT INTO PIN CHANGED")
        
        self._fire_events(ticks, bool(self._state_to_value(state)))

class Button2(HoldMixin, DigitalInputDevice):
    """
    Extends :class:`DigitalInputDevice` and represents a simple push button
    or switch.

    Connect one side of the button to a ground pin, and the other to any GPIO
    pin. Alternatively, connect one side of the button to the 3V3 pin, and the
    other to any GPIO pin, then set *pull_up* to :data:`False` in the
    :class:`Button` constructor.

    The following example will print a line of text when the button is pushed::

        from gpiozero import Button

        button = Button(4)
        button.wait_for_press()
        print("The button was pressed!")

    :type pin: int or str
    :param pin:
        The GPIO pin which the button is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :type pull_up: bool or None
    :param pull_up:
        If :data:`True` (the default), the GPIO pin will be pulled high by
        default.  In this case, connect the other side of the button to ground.
        If :data:`False`, the GPIO pin will be pulled low by default. In this
        case, connect the other side of the button to 3V3. If :data:`None`, the
        pin will be floating, so it must be externally pulled up or down and
        the ``active_state`` parameter must be set accordingly.

    :type active_state: bool or None
    :param active_state:
        See description under :class:`InputDevice` for more information.

    :type bounce_time: float or None
    :param bounce_time:
        If :data:`None` (the default), no software bounce compensation will be
        performed. Otherwise, this is the length of time (in seconds) that the
        component will ignore changes in state after an initial change.

    :param float hold_time:
        The length of time (in seconds) to wait after the button is pushed,
        until executing the :attr:`when_held` handler. Defaults to ``1``.

    :param bool hold_repeat:
        If :data:`True`, the :attr:`when_held` handler will be repeatedly
        executed as long as the device remains active, every *hold_time*
        seconds. If :data:`False` (the default) the :attr:`when_held` handler
        will be only be executed once per hold.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(
            self, pin=None, pull_up=True, active_state=None, bounce_time=None,
            hold_time=1, hold_repeat=False, pin_factory=None):
        super(Button2, self).__init__(
            pin, pull_up=pull_up, active_state=active_state,
            bounce_time=bounce_time, pin_factory=pin_factory)
        self.hold_time = hold_time
        self.hold_repeat = hold_repeat

    @property
    def value(self):
        """
        Returns 1 if the button is currently pressed, and 0 if it is not.
        """
        
        pin_str = str(self.pin)
        if(pin_str == "GPIO21"):
            global button1_state
            var = button1_state
        elif(pin_str == "GPIO26"):
            global button2_state
            var = button2_state
        elif(pin_str == "GPIO4"):
            var = button3_state
        elif(pin_str == "GPIO17"):
            var = button4_state
        elif(pin_str == "GPIO27"):
            var = button5_state
        return var

Button2.is_pressed = Button2.is_active
Button2.pressed_time = Button2.active_time
Button2.when_pressed = Button2.when_activated
Button2.when_released = Button2.when_deactivated
Button2.wait_for_press = Button2.wait_for_active
Button2.wait_for_release = Button2.wait_for_inactive

class OutputDevice(SourceMixin, GPIODevice):
    """
    Represents a generic GPIO output device.

    This class extends :class:`GPIODevice` to add facilities common to GPIO
    output devices: an :meth:`on` method to switch the device on, a
    corresponding :meth:`off` method, and a :meth:`toggle` method.

    :type pin: int or str
    :param pin:
        The GPIO pin that the device is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :param bool active_high:
        If :data:`True` (the default), the :meth:`on` method will set the GPIO
        to HIGH. If :data:`False`, the :meth:`on` method will set the GPIO to
        LOW (the :meth:`off` method always does the opposite).

    :type initial_value: bool or None
    :param initial_value:
        If :data:`False` (the default), the device will be off initially.  If
        :data:`None`, the device will be left in whatever state the pin is
        found in when configured for output (warning: this can be on).  If
        :data:`True`, the device will be switched on initially.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(
            self, pin=None, active_high=True, initial_value=False,
            pin_factory=None):
        super(OutputDevice, self).__init__(pin, pin_factory=pin_factory)
        self._lock = Lock()
        self.active_high = active_high
        if initial_value is None:
            self.pin.function = 'output'
        else:
            self.pin.output_with_state(self._value_to_state(initial_value))

    def _value_to_state(self, value):
        return bool(self._active_state if value else self._inactive_state)

    def _write(self, value):
        try:
            self.pin.state = self._value_to_state(value)
        except AttributeError:
            self._check_open()
            raise

    def on(self):
        """
        Turns the device on.
        """
        #print("it worked")
        self._write(True)

    def off(self):
        """
        Turns the device off.
        """
        self._write(False)

    def toggle(self):
        """
        Reverse the state of the device. If it's on, turn it off; if it's off,
        turn it on.
        """
        with self._lock:
            if self.is_active:
                self.off()
            else:
                self.on()

    @property
    def value(self):
        """
        Returns 1 if the device is currently active and 0 otherwise. Setting
        this property changes the state of the device.
        """
        return super(OutputDevice, self).value

    @value.setter
    def value(self, value):
        self._write(value)

    @property
    def active_high(self):
        """
        When :data:`True`, the :attr:`value` property is :data:`True` when the
        device's :attr:`~GPIODevice.pin` is high. When :data:`False` the
        :attr:`value` property is :data:`True` when the device's pin is low
        (i.e. the value is inverted).

        This property can be set after construction; be warned that changing it
        will invert :attr:`value` (i.e. changing this property doesn't change
        the device's pin state - it just changes how that state is
        interpreted).
        """
        return self._active_state

    @active_high.setter
    def active_high(self, value):
        self._active_state = True if value else False
        self._inactive_state = False if value else True

    def __repr__(self):
        try:
            return '<virtual_gpiozero.%s object on pin %r, active_high=%s, is_active=%s>' % (
                self.__class__.__name__, self.pin, self.active_high, self.is_active)
        except:
            return super(OutputDevice, self).__repr__()


class DigitalOutputDevice(OutputDevice):
    """
    Represents a generic output device with typical on/off behaviour.

    This class extends :class:`OutputDevice` with a :meth:`blink` method which
    uses an optional background thread to handle toggling the device state
    without further interaction.

    :type pin: int or str
    :param pin:
        The GPIO pin that the device is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :param bool active_high:
        If :data:`True` (the default), the :meth:`on` method will set the GPIO
        to HIGH. If :data:`False`, the :meth:`on` method will set the GPIO to
        LOW (the :meth:`off` method always does the opposite).

    :type initial_value: bool or None
    :param initial_value:
        If :data:`False` (the default), the device will be off initially.  If
        :data:`None`, the device will be left in whatever state the pin is
        found in when configured for output (warning: this can be on).  If
        :data:`True`, the device will be switched on initially.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(
            self, pin=None, active_high=True, initial_value=False,
            pin_factory=None):
        self._blink_thread = None
        self._controller = None
        super(DigitalOutputDevice, self).__init__(
            pin, active_high, initial_value, pin_factory=pin_factory
        )

    @property
    def value(self):
        #print("In value") #this printed when using led.toggle()
        return super(DigitalOutputDevice, self).value

    @value.setter
    def value(self, value):
        if(ui.comboBox_5.currentText() == "Motor (GPIO16/20)"):
            global motorForward_var
            global motorBackward_var
            motorForward_var = None
            motorBackward_var = None
            pin_str = str(self.pin)
            if(pin_str == "GPIO16"):
                motorForward_var = value
            elif(pin_str == "GPIO20"):
                motorBackward_var = value
            if(motorForward_var == None):
                motorForward_var = 0
            if(motorBackward_var == None):
               motorBackward_var = 0 
            global motor1State_var
            motor1State_var = motorForward_var - motorBackward_var
        
        self._stop_blink()
        self._write(value)

    def close(self):
        self._stop_blink()
        super(DigitalOutputDevice, self).close()

    def on(self):
        
        pin_str = str(self.pin)
        if(pin_str == "GPIO18"):
            if(ui.comboBox.currentText() == "Red LED"):
                global led1State_var
                led1State_var = 1
            elif(ui.comboBox.currentText() == "Buzzer"):
                global buzzer1State_var
                buzzer1State_var = 1
        elif(pin_str == "GPIO24"):
            global led2State_var
            led2State_var = 1
        elif(pin_str == "GPIO25"):
            global led3State_var
            led3State_var = 1
        elif(pin_str == "GPIO12"):
            global led4State_var
            led4State_var = 1
        elif(pin_str == "GPIO16"):
            global led5State_var
            led5State_var = 1
        
        self._stop_blink()
        self._write(True)

    def off(self):

        pin_str = str(self.pin)
        if(pin_str == "GPIO18"):
            if(ui.comboBox.currentText() == "Red LED"):
                global led1State_var
                led1State_var = 0
            elif(ui.comboBox.currentText() == "Buzzer"):
                global buzzer1State_var
                buzzer1State_var = 0
        elif(pin_str == "GPIO24"):
            global led2State_var
            led2State_var = 0
        elif(pin_str == "GPIO25"):
            global led3State_var
            led3State_var = 0
        elif(pin_str == "GPIO12"):
            global led4State_var
            led4State_var = 0
        elif(pin_str == "GPIO16"):
            global led5State_var
            led5State_var = 0
        
        self._stop_blink()
        self._write(False)

    def blink(self, on_time=1, off_time=1, n=None, background=True):
        """
        Make the device turn on and off repeatedly.

        :param float on_time:
            Number of seconds on. Defaults to 1 second.

        :param float off_time:
            Number of seconds off. Defaults to 1 second.

        :type n: int or None
        :param n:
            Number of times to blink; :data:`None` (the default) means forever.

        :param bool background:
            If :data:`True` (the default), start a background thread to
            continue blinking and return immediately. If :data:`False`, only
            return when the blink is finished (warning: the default value of
            *n* will result in this method never returning).
        """
        self._stop_blink()
        self._blink_thread = GPIOThread(
            target=self._blink_device, args=(on_time, off_time, n)
        )
        self._blink_thread.start()
        if not background:
            self._blink_thread.join()
            self._blink_thread = None

    def _stop_blink(self):
        if getattr(self, '_controller', None):
            self._controller._stop_blink(self)
        self._controller = None
        if getattr(self, '_blink_thread', None):
            self._blink_thread.stop()
        self._blink_thread = None

    def _blink_device(self, on_time, off_time, n):
        iterable = repeat(0) if n is None else repeat(0, n)
        for _ in iterable:
            self._write(True)
            if self._blink_thread.stopping.wait(on_time):
                break
            self._write(False)
            if self._blink_thread.stopping.wait(off_time):
                break


class LED(DigitalOutputDevice):
    """
    Extends :class:`DigitalOutputDevice` and represents a light emitting diode
    (LED).

    Connect the cathode (short leg, flat side) of the LED to a ground pin;
    connect the anode (longer leg) to a limiting resistor; connect the other
    side of the limiting resistor to a GPIO pin (the limiting resistor can be
    placed either side of the LED).

    The following example will light the LED::

        from gpiozero import LED

        led = LED(17)
        led.on()

    :type pin: int or str
    :param pin:
        The GPIO pin which the LED is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :param bool active_high:
        If :data:`True` (the default), the LED will operate normally with the
        circuit described above. If :data:`False` you should wire the cathode
        to the GPIO pin, and the anode to a 3V3 pin (via a limiting resistor).

    :type initial_value: bool or None
    :param initial_value:
        If :data:`False` (the default), the LED will be off initially.  If
        :data:`None`, the LED will be left in whatever state the pin is found
        in when configured for output (warning: this can be on).  If
        :data:`True`, the LED will be switched on initially.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    pass

LED.is_lit = LED.is_active


class Buzzer(DigitalOutputDevice):
    """
    Extends :class:`DigitalOutputDevice` and represents a digital buzzer
    component.

    .. note::

        This interface is only capable of simple on/off commands, and is not
        capable of playing a variety of tones (see :class:`TonalBuzzer`).

    Connect the cathode (negative pin) of the buzzer to a ground pin; connect
    the other side to any GPIO pin.

    The following example will sound the buzzer::

        from gpiozero import Buzzer

        bz = Buzzer(3)
        bz.on()

    :type pin: int or str
    :param pin:
        The GPIO pin which the buzzer is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :param bool active_high:
        If :data:`True` (the default), the buzzer will operate normally with
        the circuit described above. If :data:`False` you should wire the
        cathode to the GPIO pin, and the anode to a 3V3 pin.

    :type initial_value: bool or None
    :param initial_value:
        If :data:`False` (the default), the buzzer will be silent initially. If
        :data:`None`, the buzzer will be left in whatever state the pin is
        found in when configured for output (warning: this can be on). If
        :data:`True`, the buzzer will be switched on initially.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    pass

Buzzer.beep = Buzzer.blink


class PWMOutputDevice(OutputDevice):
    """
    Generic output device configured for pulse-width modulation (PWM).

    :type pin: int or str
    :param pin:
        The GPIO pin that the device is connected to. See :ref:`pin-numbering`
        for valid pin numbers. If this is :data:`None` a :exc:`GPIODeviceError`
        will be raised.

    :param bool active_high:
        If :data:`True` (the default), the :meth:`on` method will set the GPIO
        to HIGH. If :data:`False`, the :meth:`on` method will set the GPIO to
        LOW (the :meth:`off` method always does the opposite).

    :param float initial_value:
        If 0 (the default), the device's duty cycle will be 0 initially.
        Other values between 0 and 1 can be specified as an initial duty cycle.
        Note that :data:`None` cannot be specified (unlike the parent class) as
        there is no way to tell PWM not to alter the state of the pin.

    :param int frequency:
        The frequency (in Hz) of pulses emitted to drive the device. Defaults
        to 100Hz.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(
            self, pin=None, active_high=True, initial_value=0, frequency=100,
            pin_factory=None):
        self._blink_thread = None
        self._controller = None
        if not 0 <= initial_value <= 1:
            raise OutputDeviceBadValue("initial_value must be between 0 and 1")
        super(PWMOutputDevice, self).__init__(
            pin, active_high, initial_value=None, pin_factory=pin_factory
        )
        try:
            # XXX need a way of setting these together
            self.pin.frequency = frequency
            self.value = initial_value
        except:
            self.close()
            raise

    def close(self):
        try:
            self._stop_blink()
        except AttributeError:
            pass
        try:
            self.pin.frequency = None
        except AttributeError:
            # If the pin's already None, ignore the exception
            pass
        super(PWMOutputDevice, self).close()

    def _state_to_value(self, state):
        return float(state if self.active_high else 1 - state)

    def _value_to_state(self, value):
        return float(value if self.active_high else 1 - value)

    def _write(self, value):
        if not 0 <= value <= 1:
            raise OutputDeviceBadValue("PWM value must be between 0 and 1")
        super(PWMOutputDevice, self)._write(value)

    @property
    def value(self):
        """
        The duty cycle of the PWM device. 0.0 is off, 1.0 is fully on. Values
        in between may be specified for varying levels of power in the device.
        """
        return super(PWMOutputDevice, self).value

    @value.setter
    def value(self, value):
        self._stop_blink()
        self._write(value)

    def on(self):
        self._stop_blink()
        self._write(1)

    def off(self):
        self._stop_blink()
        self._write(0)

    def toggle(self):
        """
        Toggle the state of the device. If the device is currently off
        (:attr:`value` is 0.0), this changes it to "fully" on (:attr:`value` is
        1.0).  If the device has a duty cycle (:attr:`value`) of 0.1, this will
        toggle it to 0.9, and so on.
        """
        self._stop_blink()
        self.value = 1 - self.value

    @property
    def is_active(self):
        """
        Returns :data:`True` if the device is currently active (:attr:`value`
        is non-zero) and :data:`False` otherwise.
        """
        return self.value != 0

    @property
    def frequency(self):
        """
        The frequency of the pulses used with the PWM device, in Hz. The
        default is 100Hz.
        """
        return self.pin.frequency

    @frequency.setter
    def frequency(self, value):
        self.pin.frequency = value

    def blink(
            self, on_time=1, off_time=1, fade_in_time=0, fade_out_time=0,
            n=None, background=True):
        """
        Make the device turn on and off repeatedly.

        :param float on_time:
            Number of seconds on. Defaults to 1 second.

        :param float off_time:
            Number of seconds off. Defaults to 1 second.

        :param float fade_in_time:
            Number of seconds to spend fading in. Defaults to 0.

        :param float fade_out_time:
            Number of seconds to spend fading out. Defaults to 0.

        :type n: int or None
        :param n:
            Number of times to blink; :data:`None` (the default) means forever.

        :param bool background:
            If :data:`True` (the default), start a background thread to
            continue blinking and return immediately. If :data:`False`, only
            return when the blink is finished (warning: the default value of
            *n* will result in this method never returning).
        """
        self._stop_blink()
        self._blink_thread = GPIOThread(
            target=self._blink_device,
            args=(on_time, off_time, fade_in_time, fade_out_time, n)
        )
        self._blink_thread.start()
        if not background:
            self._blink_thread.join()
            self._blink_thread = None

    def pulse(self, fade_in_time=1, fade_out_time=1, n=None, background=True):
        """
        Make the device fade in and out repeatedly.

        :param float fade_in_time:
            Number of seconds to spend fading in. Defaults to 1.

        :param float fade_out_time:
            Number of seconds to spend fading out. Defaults to 1.

        :type n: int or None
        :param n:
            Number of times to pulse; :data:`None` (the default) means forever.

        :param bool background:
            If :data:`True` (the default), start a background thread to
            continue pulsing and return immediately. If :data:`False`, only
            return when the pulse is finished (warning: the default value of
            *n* will result in this method never returning).
        """
        on_time = off_time = 0
        self.blink(
            on_time, off_time, fade_in_time, fade_out_time, n, background
        )

    def _stop_blink(self):
        if self._controller:
            self._controller._stop_blink(self)
            self._controller = None
        if self._blink_thread:
            self._blink_thread.stop()
            self._blink_thread = None

    def _blink_device(
            self, on_time, off_time, fade_in_time, fade_out_time, n, fps=25):
        sequence = []
        if fade_in_time > 0:
            sequence += [
                (i * (1 / fps) / fade_in_time, 1 / fps)
                for i in range(int(fps * fade_in_time))
                ]
        sequence.append((1, on_time))
        if fade_out_time > 0:
            sequence += [
                (1 - (i * (1 / fps) / fade_out_time), 1 / fps)
                for i in range(int(fps * fade_out_time))
                ]
        sequence.append((0, off_time))
        sequence = (
                cycle(sequence) if n is None else
                chain.from_iterable(repeat(sequence, n))
                )
        for value, delay in sequence:
            self._write(value)
            if self._blink_thread.stopping.wait(delay):
                break


class Motor(SourceMixin, CompositeDevice):
    """
    Extends :class:`CompositeDevice` and represents a generic motor
    connected to a bi-directional motor driver circuit (i.e. an `H-bridge`_).

    Attach an `H-bridge`_ motor controller to your Pi; connect a power source
    (e.g. a battery pack or the 5V pin) to the controller; connect the outputs
    of the controller board to the two terminals of the motor; connect the
    inputs of the controller board to two GPIO pins.

    .. _H-bridge: https://en.wikipedia.org/wiki/H_bridge

    The following code will make the motor turn "forwards"::

        from gpiozero import Motor

        motor = Motor(17, 18)
        motor.forward()

    :type forward: int or str
    :param forward:
        The GPIO pin that the forward input of the motor driver chip is
        connected to. See :ref:`pin-numbering` for valid pin numbers. If this
        is :data:`None` a :exc:`GPIODeviceError` will be raised.

    :type backward: int or str
    :param backward:
        The GPIO pin that the backward input of the motor driver chip is
        connected to. See :ref:`pin-numbering` for valid pin numbers. If this
        is :data:`None` a :exc:`GPIODeviceError` will be raised.

    :type enable: int or str or None
    :param enable:
        The GPIO pin that enables the motor. Required for *some* motor
        controller boards. See :ref:`pin-numbering` for valid pin numbers.

    :param bool pwm:
        If :data:`True` (the default), construct :class:`PWMOutputDevice`
        instances for the motor controller pins, allowing both direction and
        variable speed control. If :data:`False`, construct
        :class:`DigitalOutputDevice` instances, allowing only direction
        control.

    :type pin_factory: Factory or None
    :param pin_factory:
        See :doc:`api_pins` for more information (this is an advanced feature
        which most users can ignore).
    """
    def __init__(self, forward=None, backward=None, enable=None, pwm=True,
                 pin_factory=None):
        if not all(p is not None for p in [forward, backward]):
            raise GPIOPinMissing(
                'forward and backward pins must be provided'
            )
        PinClass = PWMOutputDevice if pwm else DigitalOutputDevice
        devices = OrderedDict((
            ('forward_device', PinClass(forward, pin_factory=pin_factory)),
            ('backward_device', PinClass(backward, pin_factory=pin_factory)),
        ))
        if enable is not None:
            devices['enable_device'] = DigitalOutputDevice(
                enable,
                initial_value=True,
                pin_factory=pin_factory
            )
        super(Motor, self).__init__(_order=devices.keys(), **devices)

    @property
    def value(self):
        """
        Represents the speed of the motor as a floating point value between -1
        (full speed backward) and 1 (full speed forward), with 0 representing
        stopped.
        """
        
        return self.forward_device.value - self.backward_device.value

    @value.setter
    def value(self, value):
        if not -1 <= value <= 1:
            raise OutputDeviceBadValue("Motor value must be between -1 and 1")
        if value > 0:
            try:
                self.forward(value)
            except ValueError as e:
                raise OutputDeviceBadValue(e)
        elif value < 0:
            try:
               self.backward(-value)
            except ValueError as e:
                raise OutputDeviceBadValue(e)
        else:
            self.stop()

    @property
    def is_active(self):
        """
        Returns :data:`True` if the motor is currently running and
        :data:`False` otherwise.
        """
        return self.value != 0

    def forward(self, speed=1):
        """
        Drive the motor forwards.

        :param float speed:
            The speed at which the motor should turn. Can be any value between
            0 (stopped) and the default 1 (maximum speed) if *pwm* was
            :data:`True` when the class was constructed (and only 0 or 1 if
            not).
        """
        if not 0 <= speed <= 1:
            raise ValueError('forward speed must be between 0 and 1')
        if isinstance(self.forward_device, DigitalOutputDevice):
            if speed not in (0, 1):
                raise ValueError(
                    'forward speed must be 0 or 1 with non-PWM Motors')
        self.backward_device.off()
        self.forward_device.value = speed

    def backward(self, speed=1):
        """
        Drive the motor backwards.

        :param float speed:
            The speed at which the motor should turn. Can be any value between
            0 (stopped) and the default 1 (maximum speed) if *pwm* was
            :data:`True` when the class was constructed (and only 0 or 1 if
            not).
        """
        if not 0 <= speed <= 1:
            raise ValueError('backward speed must be between 0 and 1')
        if isinstance(self.backward_device, DigitalOutputDevice):
            if speed not in (0, 1):
                raise ValueError(
                    'backward speed must be 0 or 1 with non-PWM Motors')
        self.forward_device.off()
        self.backward_device.value = speed

    def reverse(self):
        """
        Reverse the current direction of the motor. If the motor is currently
        idle this does nothing. Otherwise, the motor's direction will be
        reversed at the current speed.
        """
        self.value = -self.value

    def stop(self):
        """
        Stop the motor.
        """
        self.forward_device.off()
        self.backward_device.off()

class Orientation_Sensor(object):
    def euler_angles(self): # 3-axis orientation in angular degrees
        return (ui.lcdNumber.value(),ui.lcdNumber_2.value(),ui.lcdNumber_3.value())
class Distance_Sensor(object):
    def distance(self):  # distance from bottom of sensor in millimetres (mm)
        return (ui.lcdNumber_4.value())
class Heart_Rate_Sensor(object):
    def heart_rate(self):
        return (ui.lcdNumber_6.value())
class Muscle_Sensor(object):
    def muscle_raw(self):
        return (ui.lcdNumber_7.value())
    def muscle_scaled(self,scale=10):
        self.scaled = self.muscle_raw() * scale / 255
        return self.scaled
class Gas_Sensor(object):
    def CO_gas(self):
        return (ui.lcdNumber_5.value())
    def NO2_gas(self):
        return (ui.lcdNumber_8.value())
    def H2_gas(self):
        return (lcdNumber_9.value())
    def ammonia(self,):
        return (ui.lcdNumber_19.value())
    def propane(self):
        return (ui.lcdNumber_20.value())
    def butane(self):
        return (ui.lcdNumber_21.value())
    def methane(self):
        return (ui.lcdNumber_22.value())
    def ethanol(self):
        return (ui.lcdNumber_23.value())
class Force_Sensing_Resistor(object):
    def force_raw(self):
        return (ui.lcdNumber_10.value())
    def force_scaled(self,scale=5):
        self.scaled = self.force_raw() * scale / 255
        return self.scaled
class Temperature_Sensor(object):
    def temp_array(self):
        rows, cols = (8,8)
        array = [[ui.lcdNumber_11.value()]*cols]*rows
        return array
    def temp_list(self):
        list = [ui.lcdNumber_11.value()]*64
        return list
    def avg_temp(self):
        return ui.lcdNumber_11.value()
    def max_temp(self):
        return ui.lcdNumber_11.value()
    def min_temp(self):
        return ui.lcdNumber_11.value()
    
class LedThread(QtCore.QThread):
    led1State = QtCore.pyqtSignal(int)            # define new Signal
    led2State = QtCore.pyqtSignal(int)            # define new Signal
    led3State = QtCore.pyqtSignal(int)            # define new Signal
    led4State = QtCore.pyqtSignal(int)            # define new Signal
    led5State = QtCore.pyqtSignal(int)            # define new Signal
    def __init__(self, parent=None):
        super(LedThread, self).__init__(parent)
        #self.counter = counter_start
        self.is_running = True
    def run(self):
        while True:
            time.sleep(0.01)
            self.led1State.emit(led1State_var)
            self.led2State.emit(led2State_var)
            self.led3State.emit(led3State_var)
            self.led4State.emit(led4State_var)
            self.led5State.emit(led5State_var)
            #self.led6State.emit(led6State_var)
    def stop(self):
        self.is_running = False
        print('stopping thread...')
        self.terminate()

class ButtonThread(QtCore.QThread):
    button1State = QtCore.pyqtSignal(int)            # define new Signal
    button2State = QtCore.pyqtSignal(int)            # define new Signal
    buzzer1State = QtCore.pyqtSignal(int)
    def __init__(self, parent=None):
        super(ButtonThread, self).__init__(parent)
        self.is_running = True
    def run(self):
        while True:
            time.sleep(0.01)
            self.button1State.emit(button1State_var)
            self.button2State.emit(button2State_var)
            self.buzzer1State.emit(buzzer1State_var)
    def stop(self):
        self.is_running = False
        print('stopping thread...')
        self.terminate()
        
class MotorThread(QtCore.QThread):
    motor1State  = QtCore.pyqtSignal(int)
    def __init__(self, parent=None):
        super(MotorThread, self).__init__(parent)
        self.is_running = True
    def run(self):
        while True:
            time.sleep(0.01)
            self.motor1State.emit(motor1State_var)
    def stop(self):
        self.is_running = False
        print('stopping thread...')
        self.terminate()

global button1_state, button2_state
button1_state = False
button2_state = False
global emulatorButton1, emulatorButton2
emulatorButton1 = Button2(21)
emulatorButton2 = Button2(26)

def Button(pin):
    try:
        if(str(pin) == "21"):
            return emulatorButton1
        elif(str(pin) == "26"):
            return emulatorButton2
        else:
            return Button2(pin)
    except:
            print("Setting up environment...")
            (type, value, traceback) = sys.exc_info()
            sys.excepthook(type, value, traceback)
            
class MainWindow_EXEC():
    def __init__(self):
        print("Loading... Please wait...")
        app = QtWidgets.QApplication(sys.argv)
        MainWindow = QtWidgets.QMainWindow()
        #global emulatorButton1, emulatorButton2
        #emulatorButton1 = Button2(21)
        #emulatorButton2 = Button2(26)
        #global button1_state, button2_state
        #button1_state = False
        #button2_state = False
        global led1State_var, led2State_var, led3State_var, led4State_var, led5State_var
        led1State_var = 0
        led2State_var = 0
        led3State_var = 0
        led4State_var = 0
        led5State_var = 0
        global button1State_var, button2State_var
        button1State_var = 0
        button2State_var = 0
        global buzzer1State_var
        buzzer1State_var = 0
        global motor1State_var
        motor1State_var = 0
        #this attaches the GUI signals to the above functions
        MainWindow.button1_pressed = self.button1_pressed
        MainWindow.button1_released = self.button1_released
        MainWindow.button2_pressed = self.button2_pressed
        MainWindow.button2_released = self.button2_released
        MainWindow.update_gpio18 = self.update_gpio18
        MainWindow.update_gpio24 = self.update_gpio24
        MainWindow.update_gpio25 = self.update_gpio25
        MainWindow.update_gpio12 = self.update_gpio12
        MainWindow.update_gpio16 = self.update_gpio16
        MainWindow.update_gpio21 = self.update_gpio21
        MainWindow.update_gpio26 = self.update_gpio26
        MainWindow.update_sensor = self.update_sensor
        global ui
        ui = Ui_MainWindow()
        ui.setupUi(MainWindow)
        self.hideComponents()
        self.run_thread = RunThread(parent=None)
        self.run_thread.start()
        self.led_thread = LedThread(parent=None)
        self.led_thread.start()
        self.led_thread.led1State.connect(self.setValue_led1)
        self.led_thread.led2State.connect(self.setValue_led2)
        self.led_thread.led3State.connect(self.setValue_led3)
        self.led_thread.led4State.connect(self.setValue_led4)
        self.led_thread.led5State.connect(self.setValue_led5)
        self.button_thread = ButtonThread(parent=None)
        self.button_thread.start()
        self.button_thread.button1State.connect(self.setValue_button1)
        self.button_thread.button2State.connect(self.setValue_button2)
        self.button_thread.buzzer1State.connect(self.setValue_buzzer1)
        self.motor_thread = MotorThread(parent=None)
        self.motor_thread.start()
        self.motor_thread.motor1State.connect(self.setValue_motor1)
        MainWindow.show()
        sys.exit(app.exec_())
        
    def button1_pressed(self):
        global button1_state
        global button1State_var
        if (ui.comboBox_6.currentText() != "Push Button"):
            button1_state = False
            button1State_var = 0
            emulatorButton1.pin.state = 1
        else:
            button1_state = True
            button1State_var = 1
            emulatorButton1.pin.state = 0
            emulatorButton1._fire_events(emulatorButton1.pin_factory.ticks(), bool(emulatorButton1._state_to_value(emulatorButton1.pin.state)))
    def button1_released(self):
        if (ui.comboBox_6.currentText() == "Push Button"):
            global button1_state
            global button1State_var
            button1_state = False
            button1State_var = 0
            emulatorButton1.pin.state = 1
            emulatorButton1._fire_events(emulatorButton1.pin_factory.ticks(), bool(emulatorButton1._state_to_value(emulatorButton1.pin.state)))
    def button2_pressed(self):
        global button2_state
        global button2State_var
        if (ui.comboBox_7.currentText() != "Push Button"):
            button2_state = False
            button2State_var = 0
            emulatorButton2.pin.state = 1
        else:
            button2_state = True
            button2State_var = 1
            emulatorButton2.pin.state = 0
            emulatorButton2._fire_events(emulatorButton2.pin_factory.ticks(), bool(emulatorButton2._state_to_value(emulatorButton2.pin.state)))
    def button2_released(self):
        if (ui.comboBox_7.currentText() == "Push Button"):
            global button2_state
            global button2State_var
            button2_state = False
            button2State_var = 0
            emulatorButton2.pin.state = 1
            emulatorButton2._fire_events(emulatorButton2.pin_factory.ticks(), bool(emulatorButton2._state_to_value(emulatorButton2.pin.state)))
    def setValue_led1(self,state):
        if(ui.comboBox.currentText() != "Red LED"):
            ui.progressBar_16.setValue(0)
            ui.label_147.hide()
        else:
            ui.progressBar_16.setValue(state)
            if(state):
                ui.label_147.show()
            else:
                ui.label_147.hide()
    def setValue_led2(self,state):
        if(ui.comboBox_2.currentText() == "Open"):
            ui.progressBar_17.setValue(0)
            ui.label_148.hide()
            ui.label_149.hide()
        else:
            ui.progressBar_17.setValue(state)
            if(state):
                if(ui.comboBox_2.currentText() == "Orange LED"):
                    ui.label_148.show()
                elif(ui.comboBox_2.currentText() == "Red LED"):
                    ui.label_149.show()
            else:
                if(ui.comboBox_2.currentText() == "Orange LED"):
                    ui.label_148.hide()
                elif(ui.comboBox_2.currentText() == "Red LED"):
                    ui.label_149.hide()
    def setValue_led3(self,state):
        if(ui.comboBox_3.currentText() != "Yellow LED"):
            ui.progressBar_18.setValue(0)
            ui.label_150.hide()
        else:
            ui.progressBar_18.setValue(state)
            if(state):
                ui.label_150.show()
            else:
                ui.label_150.hide()
    def setValue_led4(self,state):
        if(ui.comboBox_4.currentText() != "Green LED"):
            ui.progressBar_19.setValue(0)
            ui.label_151.hide()
        else:
            ui.progressBar_19.setValue(state)
            if(state):
                ui.label_151.show()
            else:
                ui.label_151.hide()
    def setValue_led5(self,state):
        if(ui.comboBox_5.currentText() != "Blue LED"):
            ui.progressBar_20.setValue(0)
            ui.label_152.hide()
        else:
            ui.progressBar_20.setValue(state)
            if(state):
                ui.label_152.show()
            else:
                ui.label_152.hide()
    def setValue_button1(self,state):
        if (ui.comboBox_6.currentText() != "Push Button"):
            ui.label_155.hide()
            ui.pushButton_16.setEnabled(False)
        else:
            ui.pushButton_16.setEnabled(True)
            if(state):
                ui.label_155.show()
            else:
                ui.label_155.hide()
    def setValue_button2(self,state):
        if (ui.comboBox_7.currentText() != "Push Button"):
            ui.label_156.hide()
            ui.pushButton_17.setEnabled(False)
        else:
            ui.pushButton_17.setEnabled(True)
            if(state):
                ui.label_156.show()
            else:
                ui.label_156.hide()
    def setValue_buzzer1(self, state):
        if (ui.comboBox.currentText() != "Buzzer"):
            ui.label_146.hide()
        else:
            if(state):
                ui.label_146.show()
            else:
                ui.label_146.hide()
    def setValue_motor1(self,state):
        if (ui.comboBox_5.currentText() != "Motor (GPIO16/20)"):
            ui.label_153.hide() #backward
            ui.label_154.hide() #forward
            ui.label_31.setText("")
        else:
            if(state == -1):
                ui.label_153.show() #backward
                ui.label_154.hide() #forward
                ui.label_31.setText("(BACKWARD)")
            elif(state == 0):
                ui.label_153.hide() #backward
                ui.label_154.hide() #forward
                ui.label_31.setText("")
            elif(state == 1):
                ui.label_153.hide() #backward
                ui.label_154.show() #forward
                ui.label_31.setText("(FORWARD)")
    def update_gpio18(obj, selection):
        if selection == "Open":
            ui.label_129.hide()
            ui.label_143.hide()
        elif selection == "Red LED":
            ui.label_129.show()
            ui.label_143.hide()
        elif selection == "Buzzer":
            ui.label_143.show()
            ui.label_129.hide()
    def update_gpio24(obj, selection):
        if selection == "Open":
            ui.label_130.hide()
            ui.label_144.hide()
        elif selection == "Orange LED":
            ui.label_130.show()
            ui.label_144.hide()
        elif selection == "Red LED":
            ui.label_144.show()
            ui.label_130.hide()
    def update_gpio25(obj, selection):
        if selection == "Open":
            ui.label_131.hide()
        elif selection == "Yellow LED":
            ui.label_131.show()
    def update_gpio12(obj, selection):
        if selection == "Open":
            ui.label_132.hide()
        elif selection == "Green LED":
            ui.label_132.show()
    def update_gpio16(obj, selection):
        if selection == "Open":
            ui.label_133.hide()
            ui.label_145.hide()
        elif selection == "Blue LED":
            ui.label_133.show()
            ui.label_145.hide()
        elif selection == "Motor (GPIO16/20)":
            ui.label_145.show()
            ui.label_133.hide()
    def update_gpio21(obj, selection):
        if selection == "Open":
            ui.label_134.hide()
        elif selection == "Push Button":
            ui.label_134.show()
    def update_gpio26(obj, selection):
        if selection == "Open":
            ui.label_135.hide()
        elif selection == "Push Button":
            ui.label_135.show()
    def update_sensor(obj, selection):
        if selection == "Open":
            ui.label_136.hide()
            ui.label_137.hide()
            ui.label_138.hide()
            ui.label_139.hide()
            ui.label_140.hide()
            ui.label_141.hide()
            ui.label_142.hide()
        elif selection == "Orientation":
            ui.label_136.show()
            ui.label_137.hide()
            ui.label_138.hide()
            ui.label_139.hide()
            ui.label_140.hide()
            ui.label_141.hide()
            ui.label_142.hide()
        elif selection == "Distance":
            ui.label_136.hide()
            ui.label_137.show()
            ui.label_138.hide()
            ui.label_139.hide()
            ui.label_140.hide()
            ui.label_141.hide()
            ui.label_142.hide()
        elif selection == "Gas":
            ui.label_136.hide()
            ui.label_137.hide()
            ui.label_138.show()
            ui.label_139.hide()
            ui.label_140.hide()
            ui.label_141.hide()
            ui.label_142.hide()
        elif selection == "Pulse":
            ui.label_136.hide()
            ui.label_137.hide()
            ui.label_138.hide()
            ui.label_139.show()
            ui.label_140.hide()
            ui.label_141.hide()
            ui.label_142.hide()
        elif selection == "EMG":
            ui.label_136.hide()
            ui.label_137.hide()
            ui.label_138.hide()
            ui.label_139.hide()
            ui.label_140.show()
            ui.label_141.hide()
            ui.label_142.hide()
        elif selection == "Thermal":
            ui.label_136.hide()
            ui.label_137.hide()
            ui.label_138.hide()
            ui.label_139.hide()
            ui.label_140.hide()
            ui.label_141.show()
            ui.label_142.hide()
        elif selection == "FSR":
            ui.label_136.hide()
            ui.label_137.hide()
            ui.label_138.hide()
            ui.label_139.hide()
            ui.label_140.hide()
            ui.label_141.hide()
            ui.label_142.show()
    def hideComponents(self):
        ui.label_129.hide()
        ui.label_130.hide()
        ui.label_131.hide()
        ui.label_132.hide()
        ui.label_133.hide()
        ui.label_134.hide()
        ui.label_135.hide()
        ui.label_136.hide()
        ui.label_137.hide()
        ui.label_138.hide()
        ui.label_139.hide()
        ui.label_140.hide()
        ui.label_141.hide()
        ui.label_142.hide()
        ui.label_143.hide()
        ui.label_144.hide()
        ui.label_145.hide()
        ui.label_146.hide()
        ui.label_147.hide()
        ui.label_148.hide()
        ui.label_149.hide()
        ui.label_150.hide()
        ui.label_151.hide()
        ui.label_152.hide()
        ui.label_153.hide()
        ui.label_154.hide()
        ui.label_155.hide()
        ui.label_156.hide()
        ui.label_31.setText("")
        ui.pushButton_16.setEnabled(False)
        ui.pushButton_17.setEnabled(False)
        
class RunThread(QtCore.QThread):
    
    def __init__(self, parent=None):
        super(RunThread, self).__init__(parent)
        self.is_running = True
    def run(self):
        try:
            time.sleep(0.5)
  ##########################################################################
            sensor = Heart_Rate_Sensor()
          
            file_name = 'record.txt'
            push_button = Button(21)
            buzzer = Buzzer(18)
            red_led=LED(24) 
            raw_data_list = []
            timeList = []
            rolling_avg_list = []

            #Start the monitor
            print("Welcome! Would you like to measure your resting heart rate? Press Button 1 for yes, then wait for 2 minutes for measuring your resting heart rate. ",'\n',
                  "NOTE: Please wait until your heart rate becomes stable, then start this monitor, if you were moving actively. ")
            #Call calc_resting_pulse function to measure the user's resting heart rate for 2 minutes
            while True:
                if push_button.is_pressed:
                    print("Start measuring your resting heart rate...Please try not to move for 2 minutes...")
                    data_point= sensor.heart_rate()
                    avg_rest_pulse = calc_resting_pulse()
                    print("Your resting heart rate is: ",avg_rest_pulse)
                    break

            while True:
                #Continuously input raw data every 0.5 seconds into raw_data_list
                data_point = sensor.heart_rate()
                raw_data_list.append(data_point)
                time.sleep(0.5)
                
                rolling_avg_list.append(calc_rolling_avg(raw_data_list))

                #Record instatenous time for each raw data
                time_l = time_to_list(timeList)

                #Call functions to record data to file, analyze data, and alarm user's emergency contact
                #of the user's abnormal heart rate by buzzing and flashing red LED
                data_to_file(file_name,raw_data_list,rolling_avg_list,time_l)
                print(time_l[-1],"\t",avg_rest_pulse,"\t",raw_data_list[-1],'\t',rolling_avg_list[-1],sep='')
                cont_analysis(push_button, buzzer, rolling_avg_list[-1], avg_rest_pulse, red_led)

                if rolling_avg_list[-1] == 30:
                    break

            #Map out the rolling average vs. time graph for recording
            data_to_graph(time_l,rolling_avg_list)

            return None



        except:
            (type, value, traceback) = sys.exc_info()
            sys.excepthook(type, value, traceback)
            sys.exit(1)
    def stop(self):
        self.is_running = False
        print('stopping thread...')
        self.terminate()
        

'''Objective: Set resting heart rate for individual user for later comparison.
This process lasts 2 minutes. '''
#stores pulse every .5 seconds, storing into a list
#after 2 minutes takes the average of the list, returning the average value
def calc_resting_pulse():
    sensor = Heart_Rate_Sensor()
    the_end = time.time() + 120
    resting_pulse_list = []
    while time.time() < the_end:
        data_point=sensor.heart_rate()
        resting_pulse_list.append (data_point)
        time.sleep(0.5)
    else:
        avg_rest_pulse = round(sum(resting_pulse_list)/len(resting_pulse_list),2)
    return avg_rest_pulse


'''Objective: Write instataneous time into a list. '''
def time_to_list(time_list):
    val = time.strftime('%H:%M:%S')
    time_list.append(val)                           
    return time_list


'''Objective: Calculate rolling average every 20 raw datapoints, and record into a list. '''
def calc_rolling_avg(raw_data_list):
    n = 20
    avg = 0
    if len(raw_data_list) >= n:
        avg = round(sum(raw_data_list[-n:])/n,2)
    else:
        avg = round(sum(raw_data_list)/len(raw_data_list),2)
    return avg

        
'''Objective: Write raw data, time, and rolling average to the file. '''
def data_to_file(file_name,raw_data_list,rolling_avg,time_list):
    file = open(file_name,'w')
    file.write('Time\traw data (bpm)\trolling average (bpm)\n')
    for i in range(len(raw_data_list)):
        file.write(str(time_list[i]))
        file.write('\t')
        file.write(str(raw_data_list[i]))
        file.write('\t')
        file.write(str(rolling_avg[i]))
        file.write('\n')
    file.close()

'''Objective: Process the rolling average by plotting rolling average vs. time.  '''
def data_to_graph(time_list,rolling_avg):
    fig,ax = plt.subplots(1,1)
    delta_t = time_to_s(time_list[-1]) - time_to_s(time_list[0])
    plt.xlim(0,delta_t)
    plt.ylim(min(rolling_avg)-2,max(rolling_avg)+2)
    ax.set(title = "Rolling average of heart rate in beats per minute (bpm)) vs. Time",
           xlabel = "Time (s)",
           ylabel = "Rolling average of heart rate (bpm)")
    
    for i in range(len(time_list)):
        plt.scatter(time_to_s(time_list[i])-time_to_s(time_list[0]),rolling_avg[i],c='black')
    plt.show()

'''Objective: This is for variables (i.e. time) at x-axis in the graph
generated from data_to_graph function. '''
def time_to_s(time):
    return int(str(time)[-2:]) + 60*int(str(time)[-5:-3]) + 24*60*int(str(time)[:2])

'''Objective: Process the rolling average.
Compere each rolling average with the average resting pulse.
If the rolling average is out of range,
then the buzzer and red LED will be activated to alarm abnormal heart rate.
Pressing Button 1 is required to turn off the buzzer and red LED
to continue the monitoring process. '''
def cont_analysis(push_button, buzzer, rolling_avg, avg_rest_pulse, red_led):
   
    #If the rolling average is larger than average resting pulse + 40 (upper threshold),
    #or if it is smaller than average resting pulse - 40 (lower threshold),
    #Buzzer and red LED will be activated, notifying user of abnormal pulse
    #Buzzer and LED are deactivated by the user pushing the button
    if rolling_avg < (avg_rest_pulse - 40) or rolling_avg > (avg_rest_pulse + 40):
        buzzer.on()
        red_led.on()
        print("Buzzer and red LED is on \n DANGER! CALL USER IMMEDIATELY! \n If you would like to turn off the buzzer and red LED, please press Button")
        push_button.wait_for_press()
        buzzer.off()
        red_led.off()
    

if __name__ == "__main__":
    global mainObj
    mainObj = MainWindow_EXEC()
