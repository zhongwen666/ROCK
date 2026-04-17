from rock.deployments import get_deployment
from rock.deployments.config import (
    DockerDeploymentConfig,
    LocalDeploymentConfig,
    RemoteDeploymentConfig,
)
from rock.deployments.docker import DockerDeployment
from rock.deployments.local import LocalDeployment
from rock.deployments.manager import DeploymentManager
from rock.deployments.ray import RayDeployment
from rock.deployments.remote import RemoteDeployment


def test_get_local_deployment():
    deployment = get_deployment(LocalDeploymentConfig())
    assert isinstance(deployment, LocalDeployment)


def test_get_docker_deployment():
    deployment = get_deployment(DockerDeploymentConfig(image="test"))
    assert isinstance(deployment, DockerDeployment)


def test_get_remote_deployment():
    deployment = get_deployment(RemoteDeploymentConfig())
    assert isinstance(deployment, RemoteDeployment)


async def test_deployment_manager(rock_config):
    manager = DeploymentManager(rock_config)
    config = DockerDeploymentConfig()
    docker_deployment_config = await manager.init_config(config)
    deployment = manager.get_deployment(docker_deployment_config)
    assert isinstance(deployment, RayDeployment)


class TestDeploymentManagerAutoDeleteSeconds:
    async def test_auto_delete_seconds_none_uses_rock_config(self, rock_config):
        manager = DeploymentManager(rock_config)
        config = DockerDeploymentConfig(auto_delete_seconds=None)
        result = await manager.init_config(config)
        assert result.remove_container == rock_config.sandbox_config.remove_container_enabled

    async def test_auto_delete_seconds_zero_sets_remove_container_true(self, rock_config):
        manager = DeploymentManager(rock_config)
        config = DockerDeploymentConfig(auto_delete_seconds=0)
        result = await manager.init_config(config)
        assert result.remove_container is True

    async def test_auto_delete_seconds_positive_sets_remove_container_false(self, rock_config):
        manager = DeploymentManager(rock_config)
        config = DockerDeploymentConfig(auto_delete_seconds=300)
        result = await manager.init_config(config)
        assert result.remove_container is False
