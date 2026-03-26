import asyncio
import os
import json
import stat
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.version import __version__

LOG_PATH = os.path.expanduser("~/.local/share/pcos/logs/socket_api.log")
os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
    handlers=[RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=3)]
)
logger = logging.getLogger("socket_api")

SOCKET_PATH = os.path.expanduser("~/.local/run/pcos/messaging.sock")

class SocketAPI:
    """Unix socket API for PCOS control and diagnostics."""
    
    def __init__(self, reticulum_service=None, sync_service=None, event_bus=None):
        self.reticulum_service = reticulum_service
        self.sync_service = sync_service
        self.event_bus = event_bus
        self.server = None
        self.running = False
        
    async def start(self):
        """Start the socket API server."""
        socket_dir = os.path.dirname(SOCKET_PATH)
        os.makedirs(socket_dir, exist_ok=True)
        
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        
        self.server = await asyncio.start_unix_server(
            self._handle_client,
            path=SOCKET_PATH
        )
        
        os.chmod(SOCKET_PATH, stat.S_IRUSR | stat.S_IWUSR)
        
        self.running = True
        logger.info(f"v{__version__} | Socket API started at {SOCKET_PATH}")
        
    async def stop(self):
        """Stop the socket API server."""
        self.running = False
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        if os.path.exists(SOCKET_PATH):
            os.unlink(SOCKET_PATH)
        logger.info(f"v{__version__} | Socket API stopped")
        
    async def _handle_client(self, reader, writer):
        """Handle a client connection."""
        addr = writer.get_extra_info('peername')
        logger.debug(f"Client connected: {addr}")
        
        try:
            data = await reader.read(4096)
            if not data:
                return
                
            request = json.loads(data.decode())
            response = await self._handle_request(request)
            
            writer.write(json.dumps(response).encode())
            await writer.drain()
            
        except Exception as e:
            logger.error(f"Client error: {e}")
            writer.write(json.dumps({"error": str(e)}).encode())
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            
    async def _handle_request(self, request):
        """Handle an API request."""
        cmd = request.get("cmd", "")
        
        if cmd == "peers":
            return await self._get_peers()
        elif cmd == "execute":
            return await self._execute_command(request)
        elif cmd == "status":
            return await self._get_status()
        else:
            return {"error": "unknown_command", "available": ["peers", "execute", "status"]}
            
    async def _get_peers(self):
        """Get list of discovered peers."""
        if not self.reticulum_service:
            return {"error": "service_not_available", "peers": []}
            
        peers = []
        for peer in self.reticulum_service.get_peers():
            peers.append({
                "id": peer.id,
                "name": peer.name,
                "last_seen": str(peer.last_seen) if hasattr(peer, 'last_seen') else None
            })
        return {"peers": peers}
        
    async def _execute_command(self, request):
        """Execute a command on a remote peer."""
        if not self.reticulum_service:
            return {"error": "service_not_available"}
            
        peer_id = request.get("peer", "")
        command = request.get("command", "")
        
        if not peer_id or not command:
            return {"error": "missing_peer_or_command"}
            
        target_peer = None
        for peer in self.reticulum_service.get_peers():
            if peer.name == peer_id or peer_id in peer.id:
                target_peer = peer
                break
                
        if not target_peer:
            return {"error": "peer_not_found", "peer": peer_id}
            
        logger.info(f"Executing on {target_peer.name}: {command}")
        
        try:
            result = await self.reticulum_service.execute_command(
                target_peer.id,
                command,
                timeout=request.get("timeout", 30.0)
            )
            return result if result else {"error": "execution_failed"}
        except Exception as e:
            return {"error": str(e)}
            
    async def _get_status(self):
        """Get PCOS status."""
        status = {
            "version": __version__,
            "running": self.running,
            "reticulum": "connected" if self.reticulum_service else "not_initialized",
        }
        
        if self.sync_service:
            status["sync"] = {
                "running": True,
                "files": len(self.sync_service._local_index) if hasattr(self.sync_service, '_local_index') else 0
            }
            
        return status


async def main():
    api = SocketAPI()
    await api.start()
    
    while api.running:
        await asyncio.sleep(1)
        
if __name__ == "__main__":
    asyncio.run(main())
