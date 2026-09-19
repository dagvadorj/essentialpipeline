"""
Docker utilities for EssentialPipeline
Handles container creation, execution, and cleanup
"""

import docker
import os
import tempfile
import shutil
import logging
import threading
from pathlib import Path
from typing import Optional, Dict, Any
import uuid

logger = logging.getLogger(__name__)

# Initialize Docker client
_client = None


def get_docker_client():
    """Get or create Docker client"""
    global _client
    if _client is None:
        try:
            _client = docker.from_env()
            logger.info("Docker client initialized")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise
    return _client


class DockerExecutionError(Exception):
    """Custom exception for Docker execution errors"""
    pass


class DockerContainer:
    """Manages a Docker container for task execution"""
    
    def __init__(self, image: str = 'python:3.11-slim', 
                 cpu_limit: int = 1000, 
                 memory_limit: int = 512 * 1024 * 1024,  # 512MB
                 network_mode: str = 'default',
                 working_dir: str = '/app',
                 volumes: Optional[Dict] = None,
                 environment: Optional[Dict] = None):
        """
        Initialize a Docker container
        
        Args:
            image: Docker image to use
            cpu_limit: CPU limit in millicores
            memory_limit: Memory limit in bytes
            network_mode: Network mode (default, none, host, bridge)
            working_dir: Working directory inside container
            volumes: Volume mounts {host_path: {'bind': container_path, 'mode': 'ro|rw'}}
            environment: Environment variables
        """
        self.image = image
        self.cpu_limit = cpu_limit
        self.memory_limit = memory_limit
        self.network_mode = network_mode
        self.working_dir = working_dir
        self.volumes = volumes or {}
        self.environment = environment or {}
        
        self.client = get_docker_client()
        self.container = None
        self.container_id = None
        self.run_id = str(uuid.uuid4())
        
    def _ensure_image(self) -> None:
        """
        Pull self.image if it isn't already present locally.

        containers.create() (unlike `docker run`) does not auto-pull a
        missing image - it fails with a 404 "No such image" instead.
        """
        try:
            self.client.images.get(self.image)
        except docker.errors.ImageNotFound:
            logger.info(f"Image {self.image} not found locally, pulling...")
            self.client.images.pull(self.image)
            logger.info(f"Pulled image {self.image}")

    def create_container(self, name: Optional[str] = None,
                         command: Optional[list] = None) -> str:
        """
        Create a Docker container
        
        Args:
            name: Container name (optional)
            command: Command to run (optional)
            
        Returns:
            Container ID
        """
        try:
            self._ensure_image()

            container_kwargs = {
                'image': self.image,
                'working_dir': self.working_dir,
                'detach': True,
                'cpu_period': 100000,  # Default CPU period
                'cpu_quota': self.cpu_limit,
                'mem_limit': self.memory_limit,
                'network_mode': self.network_mode,
                'volumes': self.volumes,
                'environment': self.environment,
                'labels': {
                    'essentialpipeline.run_id': self.run_id,
                    'essentialpipeline.container_type': 'execution'
                },
                'auto_remove': False
            }
            
            if name:
                container_kwargs['name'] = name
            
            if command:
                container_kwargs['command'] = command
            
            self.container = self.client.containers.create(**container_kwargs)
            self.container_id = self.container.id
            
            logger.info(f"Created container {self.container_id[:12]} with run_id {self.run_id}")
            
            return self.container_id
            
        except Exception as e:
            logger.error(f"Failed to create container: {e}")
            raise DockerExecutionError(f"Container creation failed: {e}")
    
    def start(self, command: Optional[list] = None) -> None:
        """Start the container"""
        if not self.container:
            raise DockerExecutionError("Container not created")
        
        try:
            if command:
                self.container.start(command=command)
            else:
                self.container.start()
            
            logger.info(f"Started container {self.container_id[:12]}")
        except Exception as e:
            logger.error(f"Failed to start container: {e}")
            raise DockerExecutionError(f"Container start failed: {e}")
    
    def stop(self) -> None:
        """Stop the container"""
        if not self.container:
            return
        
        try:
            self.container.stop(timeout=10)
            logger.info(f"Stopped container {self.container_id[:12]}")
        except Exception as e:
            logger.error(f"Failed to stop container: {e}")
            raise DockerExecutionError(f"Container stop failed: {e}")
    
    def remove(self) -> None:
        """Remove the container"""
        if not self.container:
            return
        
        try:
            self.container.remove(force=True)
            logger.info(f"Removed container {self.container_id[:12]}")
            self.container = None
            self.container_id = None
        except Exception as e:
            logger.error(f"Failed to remove container: {e}")
            raise DockerExecutionError(f"Container removal failed: {e}")
    
    def execute(self, command: list, 
                timeout: int = 3600, 
                return_output: bool = True) -> Dict[str, Any]:
        """
        Execute a command in the container
        
        Args:
            command: Command to execute
            timeout: Timeout in seconds
            return_output: Whether to return output
            
        Returns:
            Dict with exit_code, output, error
        """
        if not self.container:
            raise DockerExecutionError("Container not created")

        try:
            # Start container if not running
            if self.container.status != 'running':
                self.start()

            # docker-py's exec_run() has no timeout parameter of its own, so
            # it's run on a worker thread and the container is force-stopped
            # if it outlives the deadline - otherwise a runaway task script
            # would hang this thread (one of a fixed-size pool) forever.
            exec_result = {}

            def _run_exec():
                try:
                    exec_result['exit_code'], exec_result['output'] = self.container.exec_run(
                        command,
                        workdir=self.working_dir
                    )
                except Exception as exec_error:
                    exec_result['error'] = exec_error

            exec_thread = threading.Thread(target=_run_exec, daemon=True)
            exec_thread.start()
            exec_thread.join(timeout)

            if exec_thread.is_alive():
                logger.warning(
                    f"Command in container {self.container_id[:12]} exceeded {timeout}s timeout, stopping container"
                )
                self.stop()
                raise DockerExecutionError(f"Command execution timed out after {timeout}s")

            if 'error' in exec_result:
                raise exec_result['error']

            exit_code, output = exec_result['exit_code'], exec_result['output']

            result = {
                'exit_code': exit_code,
                'output': output.decode('utf-8') if output and return_output else '',
                'error': None
            }
            
            logger.info(f"Executed command in container {self.container_id[:12]}: exit_code={exit_code}")
            
            return result
            
        except DockerExecutionError:
            raise
        except docker.errors.APIError as e:
            logger.error(f"Docker API error: {e}")
            raise DockerExecutionError(f"Docker API error: {e}")
        except Exception as e:
            logger.error(f"Command execution failed: {e}")
            raise DockerExecutionError(f"Command execution failed: {e}")

    def copy_file_to_container(self, host_path: str, container_path: str) -> None:
        """
        Copy a file from host to container
        
        Args:
            host_path: Path on host
            container_path: Path in container
        """
        if not self.container:
            raise DockerExecutionError("Container not created")
        
        try:
            # Read file from host
            with open(host_path, 'rb') as f:
                file_data = f.read()
            
            # Create a temporary tar archive
            with tempfile.NamedTemporaryFile(suffix='.tar', delete=False) as tar_file:
                import tarfile
                with tarfile.open(tar_file.name, 'wb') as tar:
                    info = tarfile.TarInfo(name=container_path)
                    info.size = len(file_data)
                    tar.addfile(info, fileobj=bytes(file_data))
                
                # Copy tar to container
                with open(tar_file.name, 'rb') as f:
                    self.container.put_archive('/app', f.read())
            
            # Clean up
            os.unlink(tar_file.name)
            
            logger.info(f"Copied file to container {self.container_id[:12]}: {host_path} -> {container_path}")
            
        except Exception as e:
            logger.error(f"Failed to copy file to container: {e}")
            raise DockerExecutionError(f"File copy failed: {e}")
    
    def copy_file_from_container(self, container_path: str, host_path: str) -> None:
        """
        Copy a file from container to host
        
        Args:
            container_path: Path in container
            host_path: Path on host
        """
        if not self.container:
            raise DockerExecutionError("Container not created")
        
        try:
            # Get archive from container
            bits, stat = self.container.get_archive(container_path)
            
            # Extract tar and save file
            import tarfile
            import io
            
            with tarfile.open(fileobj=io.BytesIO(bits), mode='r:') as tar:
                for member in tar.getmembers():
                    if member.isfile():
                        # Ensure directory exists
                        os.makedirs(os.path.dirname(host_path), exist_ok=True)
                        
                        # Extract file
                        with open(host_path, 'wb') as f:
                            f.write(tar.extractfile(member).read())
            
            logger.info(f"Copied file from container {self.container_id[:12]}: {container_path} -> {host_path}")
            
        except Exception as e:
            logger.error(f"Failed to copy file from container: {e}")
            raise DockerExecutionError(f"File copy failed: {e}")
    
    def get_status(self) -> str:
        """Get container status"""
        if not self.container:
            return 'not_created'
        
        try:
            self.container.reload()
            return self.container.status
        except Exception:
            return 'unknown'
    
    def get_logs(self, stdout: bool = True, stderr: bool = True, 
                 since: Optional[int] = None) -> str:
        """
        Get container logs
        
        Args:
            stdout: Include stdout
            stderr: Include stderr
            since: Show logs since timestamp (Unix time)
            
        Returns:
            Logs as string
        """
        if not self.container:
            return ""
        
        try:
            logs = self.container.logs(
                stdout=stdout,
                stderr=stderr,
                since=since,
                follow=False,
                timestamps=True
            )
            return logs.decode('utf-8') if logs else ""
        except Exception as e:
            logger.error(f"Failed to get container logs: {e}")
            return f"Error getting logs: {e}"
    
    def cleanup(self) -> None:
        """Clean up container (stop and remove)"""
        try:
            if self.container and self.container.status == 'running':
                self.stop()
            if self.container:
                self.remove()
            logger.info(f"Cleaned up container {self.run_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup container: {e}")


def run_in_container(image: str = 'python:3.11-slim',
                      command: Optional[list] = None,
                      working_dir: str = '/app',
                      cpu_limit: int = 1000,
                      memory_limit: int = 512 * 1024 * 1024,
                      timeout: int = 3600,
                      volumes: Optional[Dict] = None,
                      environment: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Run a command in a Docker container
    
    Args:
        image: Docker image to use
        command: Command to run
        working_dir: Working directory
        cpu_limit: CPU limit in millicores
        memory_limit: Memory limit in bytes
        timeout: Timeout in seconds
        volumes: Volume mounts
        environment: Environment variables
        
    Returns:
        Dict with execution results
    """
    container = DockerContainer(
        image=image,
        cpu_limit=cpu_limit,
        memory_limit=memory_limit,
        working_dir=working_dir,
        volumes=volumes,
        environment=environment
    )
    
    try:
        # Create and start container
        container.create_container()
        
        if command:
            result = container.execute(command, timeout=timeout)
        else:
            container.start()
            result = {'exit_code': 0, 'output': '', 'error': None}
        
        # Get logs
        logs = container.get_logs()
        if logs:
            result['logs'] = logs
        
        return result
        
    finally:
        # Clean up
        container.cleanup()


def check_docker_availability() -> bool:
    """Check if Docker is available"""
    try:
        client = get_docker_client()
        client.ping()
        return True
    except Exception as e:
        logger.error(f"Docker not available: {e}")
        return False


def get_docker_info() -> Dict[str, Any]:
    """Get Docker system information"""
    try:
        client = get_docker_client()
        info = client.info()
        return {
            'containers': info.get('containers', {}),
            'images': info.get('images', []),
            'server_version': info.get('server_version', ''),
            'os': info.get('os', ''),
            'memory': info.get('mem_total', 0),
            'cpu': info.get('n_cpu', 0)
        }
    except Exception as e:
        logger.error(f"Failed to get Docker info: {e}")
        return {'error': str(e)}


def cleanup_all_containers(run_id: Optional[str] = None) -> int:
    """
    Clean up all containers created by EssentialPipeline
    
    Args:
        run_id: Specific run_id to clean up (optional)
        
    Returns:
        Number of containers cleaned up
    """
    try:
        client = get_docker_client()
        containers = client.containers.list(all=True)
        
        cleaned_count = 0
        for container in containers:
            labels = container.attrs.get('Config', {}).get('Labels', {})
            container_run_id = labels.get('essentialpipeline.run_id')
            
            if run_id and container_run_id != run_id:
                continue
            
            if labels.get('essentialpipeline.container_type') == 'execution':
                try:
                    container.remove(force=True)
                    cleaned_count += 1
                    logger.info(f"Cleaned up container {container.id[:12]}")
                except Exception as e:
                    logger.error(f"Failed to clean up container {container.id[:12]}: {e}")
        
        return cleaned_count
        
    except Exception as e:
        logger.error(f"Failed to cleanup containers: {e}")
        return 0
