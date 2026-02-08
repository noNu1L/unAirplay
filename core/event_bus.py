"""
Event Bus - Publish/Subscribe event system

This module implements the event bus that enables loose coupling between components.
Components communicate by publishing and subscribing to events.
"""
import asyncio
from typing import Callable, Dict, List, Optional, Union
from collections import defaultdict

from .events import Event, EventType
from .utils import log_debug, log_warning, log_info


# Event handler types
EventHandler = Callable[[Event], None]


class EventBus:
    """
    Event Bus - Publish/Subscribe pattern implementation

    Features:
    - Supports sync and async handlers
    - Subscribe by event type
    - Subscribe by device ID filter
    - Wildcard subscription (receive all events)
    - Singleton pattern for global access
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True

        # Handlers by event type
        self._handlers: Dict[EventType, List[EventHandler]] = defaultdict(list)

        # Wildcard handlers (receive all events)
        self._wildcard_handlers: List[EventHandler] = []

        # Handlers by device ID + event type
        self._device_handlers: Dict[str, Dict[EventType, List[EventHandler]]] = defaultdict(lambda: defaultdict(list))

        # Event loop reference
        self._loop: Optional[asyncio.AbstractEventLoop] = None

        log_info("EventBus", "Event bus initialized")

    def set_loop(self, loop: asyncio.AbstractEventLoop):
        """Set event loop for async handler execution"""
        self._loop = loop

    def subscribe(
        self,
        event_type: Union[EventType, str],
        handler: EventHandler,
        device_id: Optional[str] = None
    ):
        """
        Subscribe to events

        Args:
            event_type: Event type, or "*" for all events
            handler: Event handler function
            device_id: Optional, only receive events for this device
        """
        handler_name = getattr(handler, '__name__', str(handler))

        if event_type == "*":
            self._wildcard_handlers.append(handler)
            log_debug("EventBus", f"Subscribed to ALL events: {handler_name}")
        elif device_id:
            self._device_handlers[device_id][event_type].append(handler)
            log_debug("EventBus", f"Subscribed to {event_type.name} for device {device_id}...")
        else:
            self._handlers[event_type].append(handler)
            log_debug("EventBus", f"Subscribed to {event_type.name}: {handler_name}")

    def unsubscribe(
        self,
        event_type: Union[EventType, str],
        handler: EventHandler,
        device_id: Optional[str] = None
    ):
        """Unsubscribe from events"""
        try:
            if event_type == "*":
                self._wildcard_handlers.remove(handler)
            elif device_id:
                self._device_handlers[device_id][event_type].remove(handler)
            else:
                self._handlers[event_type].remove(handler)
        except ValueError:
            pass

    def unsubscribe_device(self, device_id: str):
        """Unsubscribe all handlers for a device"""
        if device_id in self._device_handlers:
            del self._device_handlers[device_id]
            log_debug("EventBus", f"Unsubscribed all handlers for device {device_id}...")

    def publish(self, event: Event):
        """
        Publish event (synchronous)

        Event is dispatched to:
        1. Wildcard handlers
        2. Event type handlers
        3. Device-specific handlers (if device_id matches)
        """
        # Log event publish with trace_id
        device_info = event.device_id if event.device_id else "global"
        extra_info = ""
        if event.type == EventType.STATE_CHANGED:
            extra_info = f" state={event.data.get('state', '?')}"
        log_debug("EventBus", f"[{event.trace_id}] Publish: {event.type.name} -> {device_info}{extra_info}")

        handlers_to_call = []

        # Collect wildcard handlers
        handlers_to_call.extend(self._wildcard_handlers)

        # Collect event type handlers
        handlers_to_call.extend(self._handlers.get(event.type, []))

        # Collect device-specific handlers
        if event.device_id:
            device_handlers = self._device_handlers.get(event.device_id, {})
            handlers_to_call.extend(device_handlers.get(event.type, []))

        # Call all handlers
        for handler in handlers_to_call:
            try:
                handler_name = getattr(handler, '__name__', str(handler))
                log_debug("EventBus", f"[{event.trace_id}] Handle: {event.type.name} -> {handler_name}")
                result = handler(event)
                # If coroutine, schedule to event loop
                if asyncio.iscoroutine(result):
                    if self._loop and self._loop.is_running():
                        asyncio.run_coroutine_threadsafe(result, self._loop)
                    else:
                        # Try to get current loop
                        try:
                            loop = asyncio.get_event_loop()
                            if loop.is_running():
                                asyncio.ensure_future(result, loop=loop)
                            else:
                                loop.run_until_complete(result)
                        except RuntimeError:
                            pass
            except Exception as e:
                handler_name = getattr(handler, '__name__', str(handler))
                log_warning("EventBus", f"[{event.trace_id}] Handler error ({handler_name}): {e}")

    async def publish_async(self, event: Event):
        """Publish event (asynchronous)"""
        # Log event publish with trace_id
        device_info = event.device_id if event.device_id else "global"
        extra_info = ""
        if event.type == EventType.STATE_CHANGED:
            extra_info = f" state={event.data.get('state', '?')}"
        log_debug("EventBus", f"[{event.trace_id}] Publish(async): {event.type.name} -> {device_info}{extra_info}")

        handlers_to_call = []

        handlers_to_call.extend(self._wildcard_handlers)
        handlers_to_call.extend(self._handlers.get(event.type, []))

        if event.device_id:
            device_handlers = self._device_handlers.get(event.device_id, {})
            handlers_to_call.extend(device_handlers.get(event.type, []))

        # Collect async tasks
        tasks = []
        for handler in handlers_to_call:
            try:
                handler_name = getattr(handler, '__name__', str(handler))
                log_debug("EventBus", f"[{event.trace_id}] Handle: {event.type.name} -> {handler_name}")
                result = handler(event)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception as e:
                handler_name = getattr(handler, '__name__', str(handler))
                log_warning("EventBus", f"[{event.trace_id}] Handler error ({handler_name}): {e}")

        # Execute all async handlers concurrently
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def clear(self):
        """Clear all subscriptions"""
        self._handlers.clear()
        self._wildcard_handlers.clear()
        self._device_handlers.clear()
        log_info("EventBus", "All subscriptions cleared")


# Global event bus instance
event_bus = EventBus()
