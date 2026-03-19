"""Event system for inter-service communication."""
import asyncio
from typing import Callable, Dict, List, Any
from dataclasses import dataclass, field
from datetime import datetime
import logging


logger = logging.getLogger(__name__)


@dataclass
class Event:
    """Base event class."""
    type: str
    data: Any = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "system"


class EventBus:
    """Event bus for publish-subscribe communication between services."""
    
    def __init__(self):
        """Initialize event bus."""
        self._subscribers: Dict[str, List[Callable]] = {}
        self._event_history: List[Event] = []
        self._max_history = 100
    
    def subscribe(self, event_type: str, callback: Callable):
        """Subscribe to an event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to event: {event_type}")
    
    def unsubscribe(self, event_type: str, callback: Callable):
        """Unsubscribe from an event type."""
        if event_type in self._subscribers:
            self._subscribers[event_type].remove(callback)
    
    async def publish(self, event: Event):
        """Publish an event to all subscribers."""
        logger.info(f"[EVENT BUS] Publishing: {event.type} from {event.source}")
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        logger.debug(f"Publishing event: {event.type}")
        
        if event.type in self._subscribers:
            logger.info(f"[EVENT BUS] Found {len(self._subscribers[event.type])} subscribers for {event.type}")
            for callback in self._subscribers[event.type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except Exception as e:
                    logger.error(f"Error in event callback: {e}")
    
    def publish_sync(self, event: Event):
        """Publish an event synchronously."""
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        if event.type in self._subscribers:
            for callback in self._subscribers[event.type]:
                try:
                    callback(event)
                except Exception as e:
                    logger.error(f"Error in event callback: {e}")
    
    def get_history(self, event_type: str = None, limit: int = 10) -> List[Event]:
        """Get event history."""
        if event_type:
            events = [e for e in self._event_history if e.type == event_type]
        else:
            events = self._event_history
        return events[-limit:]


# Global event bus instance
event_bus = EventBus()


# Event types
class Events:
    """Event type constants."""
    PEER_DISCOVERED = "peer.discovered"
    PEER_LOST = "peer.lost"
    PEER_UPDATED = "peer.updated"
    
    SYNC_STARTED = "sync.started"
    SYNC_COMPLETED = "sync.completed"
    SYNC_FAILED = "sync.failed"
    SYNC_PROGRESS = "sync.progress"
    CONFLICT_DETECTED = "sync.conflict"
    
    CONTAINER_STARTING = "container.starting"
    CONTAINER_STARTED = "container.started"
    CONTAINER_STOPPING = "container.stopping"
    CONTAINER_STOPPED = "container.stopped"
    CONTAINER_ERROR = "container.error"
    
    APP_LAUNCHED = "app.launched"
    APP_CLOSED = "app.closed"
    
    STATUS_UPDATE = "system.status"
