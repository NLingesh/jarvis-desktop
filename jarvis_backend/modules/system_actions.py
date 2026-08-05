import re
import subprocess
import psutil
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


SHELL_METACHARACTERS = re.compile(r"[;&|><`$()]")


class SystemActions:
    def __init__(self):
        self.allowed_commands = [
            "echo", "ls", "pwd", "whoami", "date",
            "uptime", "df", "free", "ps", "top"
        ]

    def get_system_info(self) -> Dict:
        """Get comprehensive system information"""
        try:
            return {
                "hostname": self._get_hostname(),
                "os": self._get_os(),
                "cpu": self._get_cpu_info(),
                "memory": self._get_memory_info(),
                "disk": self._get_disk_info(),
                "uptime": self._get_uptime(),
                "network": self._get_network_info()
            }
        except Exception as e:
            logger.error(f"Failed to get system info: {e}")
            return {}

    def _get_hostname(self) -> str:
        """Get system hostname"""
        try:
            return subprocess.check_output(
                ["hostname"],
                text=True
            ).strip()
        except:
            return "Unknown"

    def _get_os(self) -> Dict:
        """Get OS information"""
        try:
            import platform
            return {
                "system": platform.system(),
                "release": platform.release(),
                "version": platform.version(),
                "platform": platform.platform()
            }
        except:
            return {}

    def _get_cpu_info(self) -> Dict:
        """Get CPU information"""
        try:
            return {
                "count": psutil.cpu_count(),
                "percent": psutil.cpu_percent(interval=1),
                "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else {}
            }
        except:
            return {}

    def _get_memory_info(self) -> Dict:
        """Get memory information"""
        try:
            memory = psutil.virtual_memory()
            return {
                "total": memory.total,
                "available": memory.available,
                "percent": memory.percent,
                "used": memory.used,
                "free": memory.free
            }
        except:
            return {}

    def _get_disk_info(self) -> Dict:
        """Get disk information"""
        try:
            disk = psutil.disk_usage("/")
            return {
                "total": disk.total,
                "used": disk.used,
                "free": disk.free,
                "percent": disk.percent
            }
        except:
            return {}

    def _get_uptime(self) -> float:
        """Get system uptime in seconds"""
        try:
            with open("/proc/uptime", "r") as f:
                return float(f.readline().split()[0])
        except:
            return 0.0

    def _get_network_info(self) -> Dict:
        """Get network information"""
        try:
            net = psutil.net_if_stats()
            return {
                "interfaces": list(net.keys()),
                "stats": {name: stats._asdict() for name, stats in net.items()}
            }
        except:
            return {}

    async def execute_command(self, command: str) -> str:
        """Execute a safe system command"""
        try:
            if SHELL_METACHARACTERS.search(command):
                return "Command not allowed: shell metacharacters detected"

            cmd_parts = command.split()
            if not cmd_parts or cmd_parts[0] not in self.allowed_commands:
                return "Command not allowed"

            result = subprocess.run(
                cmd_parts,
                shell=False,
                capture_output=True,
                text=True,
                timeout=10
            )

            return result.stdout if result.returncode == 0 else result.stderr

        except subprocess.TimeoutExpired:
            return "Command timed out"
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            return f"Error: {str(e)}"
    
    async def get_processes(self) -> List[Dict]:
        """Get list of running processes"""
        try:
            processes = []
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                try:
                    processes.append({
                        "pid": proc.info["pid"],
                        "name": proc.info["name"],
                        "cpu_percent": proc.info["cpu_percent"],
                        "memory_percent": proc.info["memory_percent"]
                    })
                except:
                    continue
            
            # Sort by memory usage
            processes.sort(key=lambda x: x["memory_percent"], reverse=True)
            return processes[:10]  # Top 10
        
        except Exception as e:
            logger.error(f"Failed to get processes: {e}")
            return []
    
    async def get_open_ports(self) -> List[Dict]:
        """Get list of open network ports"""
        try:
            connections = psutil.net_connections()
            ports = []
            
            for conn in connections:
                if conn.laddr:
                    ports.append({
                        "ip": conn.laddr.ip,
                        "port": conn.laddr.port,
                        "status": conn.status,
                        "type": conn.type
                    })
            
            return ports
        
        except Exception as e:
            logger.error(f"Failed to get open ports: {e}")
            return []
    
    async def restart_service(self, service_name: str) -> bool:
        """Restart a system service"""
        try:
            # Requires sudo/admin privileges
            result = subprocess.run(
                ["sudo", "systemctl", "restart", service_name],
                capture_output=True,
                timeout=30
            )
            return result.returncode == 0
        except Exception as e:
            logger.error(f"Failed to restart service: {e}")
            return False
    
    async def open_application(self, app_name: str) -> bool:
        """Open an application (whitelist-validated)"""
        import shlex
        try:
            if SHELL_METACHARACTERS.search(app_name):
                return False
            if not app_name or len(app_name) > 100:
                return False
            if '/' in app_name or '\\' in app_name:
                return False
            allowed_apps = {
                "firefox", "chrome", "chromium", "chromium-browser",
                "thunderbird", "evolution", "nautilus", "dolphin",
                "code", "code-oss", "vim", "nvim", "nano", "gedit",
                "terminal", "konsole", "alacritty", "kitty", "tilix",
                "libreoffice", "libreoffice-writer", "libreoffice-calc",
                "vlc", "audacious", "rhythmbox", "spotify",
                "gnome-settings", "systemsettings", "blender", "gimp",
                "inkscape", "file-roller", "evince", "okular",
            }
            if app_name not in allowed_apps:
                return False
            subprocess.Popen([app_name])
            logger.info(f"Opening application: {app_name}")
            return True
        except Exception as e:
            logger.error(f"Failed to open application: {e}")
            return False
