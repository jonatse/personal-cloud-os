import asyncio
import os
import json
import stat
import logging
from logging.handlers import RotatingFileHandler
import sys
import time
import threading
import socket

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
    
    def __init__(self, reticulum_service=None, sync_service=None, event_bus=None, app=None):
        self.reticulum_service = reticulum_service
        self.sync_service = sync_service
        self.event_bus = event_bus
        self.app = app  # Reference to main app for accessing services
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
            
            writer.write(json.dumps(response).encode() + b'\n')
            await writer.drain()
            
        except Exception as e:
            logger.error(f"Client error: {e}")
            writer.write(json.dumps({"error": str(e)}).encode() + b'\n')
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
        elif cmd == "sync":
            return await self._get_sync()
        elif cmd == "network":
            return await self._get_network()
        elif cmd == "device":
            return await self._get_device()
        elif cmd == "container":
            return await self._get_container()
        elif cmd == "logs":
            return await self._get_logs(request)
        elif cmd == "identity":
            return await self._get_identity()
        elif cmd == "circle":
            return await self._get_circle(request)
        elif cmd == "link":
            return await self._get_link(request)
        elif cmd == "service_start":
            return await self._service_start(request)
        elif cmd == "service_stop":
            return await self._service_stop(request)
        elif cmd == "service_restart":
            return await self._service_restart(request)
        else:
            return {"error": "unknown_command", "available": ["peers", "execute", "status", "sync", "network", "device", "container", "logs", "identity", "circle", "link", "service_start", "service_stop", "service_restart"]}
            
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

    async def _get_sync(self):
        """Get sync status."""
        if not self.sync_service:
            return {"error": "service_not_available"}
        
        try:
            status = self.sync_service.get_status()
            return {
                "state": status.state,
                "files_synced": status.files_synced,
                "files_local": status.files_local,
                "sync_dir": self.sync_service.sync_dir if hasattr(self.sync_service, 'sync_dir') else "unknown"
            }
        except Exception as e:
            return {"error": str(e)}

    async def _get_network(self):
        """Get network information."""
        import subprocess
        
        result = {
            "hostname": socket.gethostname(),
        }
        
        # Reticulum info
        if self.reticulum_service:
            try:
                result["reticulum"] = {
                    "identity": getattr(self.reticulum_service, '_identity_hash', 'Unknown')[:32] + "..." if hasattr(self.reticulum_service, '_identity_hash') else "unknown",
                    "destination": getattr(self.reticulum_service, '_destination_hash', 'Unknown')[:32] + "..." if hasattr(self.reticulum_service, '_destination_hash') else "unknown",
                    "running": self.reticulum_service.is_running()
                }
            except Exception as e:
                result["reticulum"] = {"error": str(e)}
        
        # Network interfaces via psutil
        try:
            import psutil
            interfaces = {}
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            for iface in addrs:
                if iface == 'lo':
                    continue
                ipv4 = next((a.address for a in addrs[iface] if a.family == 2), None)
                mac = next((a.address for a in addrs[iface] if a.family == 17), None)
                st = stats.get(iface)
                interfaces[iface] = {
                    "ip": ipv4 or "N/A",
                    "mac": mac or "N/A",
                    "up": st.isup if st else False,
                    "speed": f"{st.speed}M" if st and st.speed else "N/A"
                }
            result["interfaces"] = interfaces
        except ImportError:
            result["interfaces"] = {"error": "psutil not available"}
        except Exception as e:
            result["interfaces"] = {"error": str(e)}
        
        # Bluetooth
        try:
            if os.path.exists("/sys/class/bluetooth"):
                devs = os.listdir("/sys/class/bluetooth")
                result["bluetooth"] = {"devices": devs, "status": "present"} if devs else {"status": "not detected"}
            else:
                result["bluetooth"] = {"status": "not detected"}
        except Exception as e:
            result["bluetooth"] = {"error": str(e)}
        
        # Audio (PulseAudio/PipeWire)
        try:
            r = subprocess.run(["pactl", "list", "short", "sinks"], capture_output=True, text=True, timeout=3)
            r2 = subprocess.run(["pactl", "list", "short", "sources"], capture_output=True, text=True, timeout=3)
            sinks = [l for l in r.stdout.splitlines() if l.strip()]
            sources = [l for l in r2.stdout.splitlines() if l.strip()]
            result["audio"] = {
                "sinks": len(sinks),
                "sources": len(sources),
                "status": "running"
            }
        except FileNotFoundError:
            result["audio"] = {"status": "not available"}
        except Exception as e:
            result["audio"] = {"error": str(e)}
        
        # I2P
        if self.app and hasattr(self.app, 'i2p_manager'):
            try:
                i2p = self.app.i2p_manager
                status = i2p.status()
                result["i2p"] = {
                    "available": status.get("available", False),
                    "we_started": status.get("we_started", False),
                    "sam_host": status.get("sam_host"),
                    "sam_port": status.get("sam_port")
                }
            except Exception as e:
                result["i2p"] = {"error": str(e)}
        else:
            result["i2p"] = {"status": "not available"}
        
        return result

    async def _get_device(self):
        """Get device information."""
        return {
            "hostname": socket.gethostname(),
            "user": os.environ.get('USER', 'unknown'),
            "platform": sys.platform,
            "version": __version__
        }

    async def _get_container(self):
        """Get container status."""
        if not self.app or not hasattr(self.app, 'container_manager'):
            return {"error": "container_manager_not_available"}
        
        try:
            container = self.app.container_manager
            return {
                "running": container.is_running(),
                "ssh_port": 2222 if container.is_running() else None
            }
        except Exception as e:
            return {"error": str(e)}

    async def _get_logs(self, request):
        """Get application logs."""
        log_path = os.path.expanduser('~/.local/share/pcos/logs/app.log')
        num_lines = request.get("lines", 50)
        level = request.get("level", None)
        
        if not os.path.exists(log_path):
            return {"error": "log_file_not_found"}
        
        level_priority = {'DEBUG': 0, 'INFO': 1, 'WARNING': 2, 'ERROR': 3}
        min_level = level_priority.get(level, -1)
        
        try:
            with open(log_path, 'r') as f:
                lines = f.readlines()
            
            filtered = []
            for line in lines[-num_lines:]:
                if level:
                    for lvl in ['DEBUG', 'INFO', 'WARNING', 'ERROR']:
                        if lvl in line and level_priority[lvl] >= min_level:
                            filtered.append(line.rstrip())
                            break
                else:
                    filtered.append(line.rstrip())
            
            return {"logs": filtered[-num_lines:]}
        except Exception as e:
            return {"error": str(e)}

    async def _get_identity(self, request=None):
        """Get or manage identity info."""
        subcmd = (request.get("subcommand") if request else None) if request else "show"
        
        try:
            from core.identity import IdentityManager
            id_mgr = IdentityManager()
            
            if subcmd == "show":
                id_mgr.load_or_create_identity()
                return {
                    "hash": id_mgr.get_identity_hash()[:32] + "...",
                    "path": id_mgr.get_identity_path(),
                    "trust_level": id_mgr.get_trust_level(id_mgr.get_identity_hash())
                }
            elif subcmd == "create":
                if os.path.exists(id_mgr.get_identity_path()):
                    return {"error": "identity_exists", "message": "Identity already exists. Use 'identity show' to view."}
                id_mgr.load_or_create_identity()
                return {"status": "created", "hash": id_mgr.get_identity_hash()[:32] + "..."}
            elif subcmd == "export":
                id_mgr.load_or_create_identity()
                exported = id_mgr.export_identity()
                return {"identity": exported}
            elif subcmd == "import":
                identity_base64 = request.get("identity", "")
                if not identity_base64:
                    return {"error": "missing_identity_data"}
                identity = id_mgr.import_identity(identity_base64)
                return {"status": "imported", "hash": identity.hash.hex()[:32] + "..."}
            else:
                return {"error": "unknown_subcommand", "available": ["show", "create", "export", "import"]}
        except Exception as e:
            return {"error": str(e)}

    async def _get_circle(self, request):
        """Get or manage circle info."""
        subcmd = request.get("subcommand", "list")
        
        try:
            from core.identity import IdentityManager
            id_mgr = IdentityManager()
            
            if subcmd == "list":
                circles = id_mgr.list_circles()
                return {"circles": circles}
            elif subcmd == "create":
                name = request.get("name", "")
                if not name:
                    return {"error": "missing_circle_name"}
                circle_identity = id_mgr.create_circle(name)
                return {"status": "created", "name": name, "identity": circle_identity.hash.hex()[:32] + "..."}
            elif subcmd == "show":
                name = request.get("name", "")
                if not name:
                    return {"error": "missing_circle_name"}
                circle_identity = id_mgr.get_circle(name)
                if not circle_identity:
                    return {"error": "circle_not_found", "name": name}
                # Get members
                members = []
                members_file = os.path.join(id_mgr._circles_dir, name, "members.json")
                if os.path.exists(members_file):
                    import json
                    with open(members_file, "r") as f:
                        members = json.load(f)
                return {
                    "name": name,
                    "identity": circle_identity.hash.hex()[:32] + "...",
                    "members": members
                }
            elif subcmd == "add":
                name = request.get("name", "")
                identity_base64 = request.get("identity", "")
                if not name or not identity_base64:
                    return {"error": "missing_name_or_identity"}
                success = id_mgr.add_to_circle(name, identity_base64)
                return {"status": "added" if success else "failed", "name": name}
            elif subcmd == "remove":
                name = request.get("name", "")
                identity_hash = request.get("identity", "")
                if not name or not identity_hash:
                    return {"error": "missing_name_or_identity"}
                success = id_mgr.remove_from_circle(name, identity_hash)
                return {"status": "removed" if success else "failed", "name": name}
            else:
                return {"error": "unknown_subcommand", "available": ["list", "create", "show", "add", "remove"]}
        except Exception as e:
            return {"error": str(e)}

    async def _get_link(self, request):
        """Get link status."""
        subcmd = request.get("subcommand", "list")
        
        if not self.sync_service:
            return {"error": "sync_service_not_available"}
        
        try:
            links = getattr(self.sync_service, '_links', {})
            
            if subcmd == "list":
                result = []
                for peer_id, link in links.items():
                    result.append({
                        "peer_id": peer_id.hex()[:16] + "...",
                        "status": str(link.status),
                        "rtt": link.rtt if hasattr(link, 'rtt') else None
                    })
                return {"links": result}
            else:
                return {"error": "unknown_subcommand", "available": ["list"]}
        except Exception as e:
            return {"error": str(e)}


    async def _service_start(self, request):
        """Start a service."""
        service = request.get("service", "")
        valid = ['peers', 'sync', 'container', 'i2p', 'all']
        
        if service not in valid:
            return {"error": "invalid_service", "valid": valid}
        
        if not self.app:
            return {"error": "app_not_available"}
        
        import asyncio
        try:
            if service == 'all':
                await self.app.reticulum_service.start()
                await self.app.sync_engine.start()
                if hasattr(self.app, 'container_manager'):
                    await self.app.container_manager.start()
                if hasattr(self.app, 'i2p_manager'):
                    await self.app.i2p_manager.start()
            elif service == 'peers':
                await self.app.reticulum_service.start()
            elif service == 'sync':
                await self.app.sync_engine.start()
            elif service == 'container':
                if hasattr(self.app, 'container_manager'):
                    await self.app.container_manager.start()
                else:
                    return {"error": "container_not_available"}
            elif service == 'i2p':
                if hasattr(self.app, 'i2p_manager'):
                    await self.app.i2p_manager.start()
                else:
                    return {"error": "i2p_not_available"}
            return {"status": "started", "service": service}
        except Exception as e:
            return {"error": str(e)}

    async def _service_stop(self, request):
        """Stop a service."""
        service = request.get("service", "")
        valid = ['peers', 'sync', 'container', 'i2p', 'all']
        
        if service not in valid:
            return {"error": "invalid_service", "valid": valid}
        
        if not self.app:
            return {"error": "app_not_available"}
        
        import asyncio
        try:
            if service == 'all':
                if hasattr(self.app, 'i2p_manager'):
                    await self.app.i2p_manager.stop()
                if hasattr(self.app, 'sync_engine'):
                    await self.app.sync_engine.stop()
                if hasattr(self.app, 'reticulum_service'):
                    await self.app.reticulum_service.stop()
                if hasattr(self.app, 'container_manager'):
                    await self.app.container_manager.stop()
            elif service == 'peers':
                await self.app.reticulum_service.stop()
            elif service == 'sync':
                await self.app.sync_engine.stop()
            elif service == 'container':
                if hasattr(self.app, 'container_manager'):
                    await self.app.container_manager.stop()
                else:
                    return {"error": "container_not_available"}
            elif service == 'i2p':
                if hasattr(self.app, 'i2p_manager'):
                    await self.app.i2p_manager.stop()
                else:
                    return {"error": "i2p_not_available"}
            return {"status": "stopped", "service": service}
        except Exception as e:
            return {"error": str(e)}

    async def _service_restart(self, request):
        """Restart a service."""
        service = request.get("service", "")
        
        if not self.app:
            return {"error": "app_not_available"}
        
        import asyncio
        # Stop first
        stop_req = {"service": service}
        stop_resp = await self._service_stop(stop_req)
        if "error" in stop_resp:
            return stop_resp
        
        # Then start
        start_resp = await self._service_start(request)
        if "error" in start_resp:
            return start_resp
        
        return {"status": "restarted", "service": service}


async def main():
    api = SocketAPI()
    await api.start()
    
    while api.running:
        await asyncio.sleep(1)
        
if __name__ == "__main__":
    asyncio.run(main())
