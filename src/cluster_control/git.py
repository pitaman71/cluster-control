#! env python3

from __future__ import annotations

import os
import json
import typing
from urllib.request import Request, urlopen

from . import configurable
from . import file
from . import resource
from . import ssl_security

class GithubDeployKey(resource.Resource):
    """Resource representing an RSA key pair registed with github to enable git repo read access for deployment purposes"""
    owner: configurable.Var[str]
    repo: configurable.Var[str]
    repo_key_id: configurable.Var[str]

    ssl_key: resource.Ref[ssl_security.RSAKey]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.owner = configurable.Var(self, 'owner')
        self.repo = configurable.Var(self, 'repo')
        self.repo_key_id = configurable.Var(self, 'repo_key_id')

        self.ssl_key = resource.Ref(self, 'ssl_key')

    def url(self):
        return f'git@github.com:{self.owner}/{self.repo}.git'

    def elaborate(self, phase: resource.Phase):
        self.ssl_key.resolve(phase, ssl_security.RSAKey)
        self.ssl_key().alias(
            path=self.owner()+'-' + self.repo() + '.rsa',
            bits=2048
        )
        super().elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.repo_key_id:
            print(f"{self} : already registered deploy key for read access to github repo {self.owner}/{self.repo}")
        elif not self.ssl_key:
            raise RuntimeError(f"{self} : public_key has not been generated yet")
        else:
            with phase.sub(f"{self} : registering deploy key for read access to github repo {self.owner}/{self.repo}") as phase:
                create_key_params = json.dumps({
                    'key': 'ssh-rsa '+self.ssl_key().public().contents().decode('utf-8'),
                    'read_only': True
                }).encode('utf-8')
                authorization = 'token ' + os.environ["GITHUB_PASSWORD"]
                request = Request(
                    f'https://api.github.com/repos/{self.owner()}/{self.repo()}/keys', 
                    method='POST', headers={ 'Authorization': authorization })
                with urlopen(request, data=create_key_params) as resp:
                    if resp.status >= 300 or resp.status < 200:
                        raise RuntimeError(resp.read().decode('utf-8'))
                    else:
                        asJSON = json.load(resp)
                        if 'id' not in asJSON:
                            raise RuntimeError('Malformed response from github did not contain key id: '+json.dumps(asJSON))
                        self.repo_key_id = asJSON['id']

    def down(self, phase: resource.Phase):
        if self.repo_key_id:
            with phase.sub(f"{self} : un-registering deploy key for read access to github repo {self.owner}/{self.repo}") as phase:
                authorization = 'token ' + os.environ["GITHUB_PASSWORD"]
                request = Request(
                    f'https://api.github.com/repos/{self.owner()}/{self.repo()}/keys/{self.repo_key_id()}', 
                    method='DELETE',
                    headers={ 'Authorization': authorization
                })
                with urlopen(request) as resp:
                    if resp.status >= 300 or resp.status < 200:
                        raise RuntimeError(resp.read().decode('utf-8'))
                    else:
                        self.repo_key_id.clear()

class GitDeploy(resource.Resource):
    """Resource representing deployment of code from git as a clone on an instance"""
    owner: configurable.Var[str]
    repo: configurable.Var[str]
    is_installed: configurable.Var[bool]

    instance: resource.Ref[resource.Instance]
    deploy_key: resource.Ref[GithubDeployKey]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.owner = configurable.Var(self, 'owner')
        self.repo = configurable.Var(self, 'repo')
        self.is_installed = configurable.Var(self, 'is_installed')

        self.instance = resource.Ref(self, 'instance')
        self.deploy_key = resource.Ref(self, 'deploy_key')

    def url(self):
        return f'git@github.com:{self.owner()}/{self.repo()}.git'

    def deploy_key_remote_path(self):
        return f"{self.name}.pvt-repo-key.pem"

    def upload_key(self, phase: resource.Phase):
        with phase.sub(f"{self} : installing deploy key {self.deploy_key().name} on {self.instance}") as phase:
            deploy_key = file.Transfer([ *(self.path()), f"deploy-key-install" ]).alias(
                image=self.deploy_key().ssl_key().private,
                remote=file.RemoteFile([ * (self.path()), f"deploy-key-remote_file" ]).alias(
                    instance=self.instance,
                    remote_path=self.deploy_key_remote_path(),
                    mode='0600'
                )
            )
            deploy_key.put()

    def elaborate(self, phase: resource.Phase):
        self.deploy_key.resolve(phase, GithubDeployKey)
        super().elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.is_installed and self.is_installed:
            print(f"{self} : git deployment {self.instance} of {self.repo}/{self.owner} already exists")
        elif not self.name:
            raise RuntimeError("name is not selected")
        else:
            self.upload_key(phase)
            instance = self.instance()
            with phase.sub(f"{self} : cloning repo {self.repo}/{self.owner} on {self.instance}") as phase:
                instance.execute(['rm', '-f', self.repo() ], 60)
                instance.execute(['git', 'config', '--global', 'core.sshCommand', f"""'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i {self.deploy_key_remote_path()}'"""], 60)
                instance.execute(['git', 'clone', self.url(), self.repo()], 60)
                self.is_installed.select(True)

    def down(self, phase: resource.Phase):
        if not self.name:
            raise RuntimeError("name is not selected")
        if self.is_installed:
            instance = self.instance()
            with phase.sub(f"{self} : deleting cloneof repo {self.repo}/{self.owner} on {self.instance}") as phase:
                instance.execute(['sudo', 'rm', '-rf', self.repo() ], 60)
                self.is_installed.select(False)

    def pull(self, phase: resource.Phase):
        if not self.name:
            raise RuntimeError("name is not selected")
        if self.is_installed:
            self.upload_key(phase)
            instance = self.instance()
            instance.execute(['git', 'config', '--global', 'core.sshCommand', f"""'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no -i {self.deploy_key_remote_path()}'"""], 60)
            instance.execute(['git', 'remote', 'show', 'origin' ], timeout=60, cwd=self.name)
            instance.execute(['git', 'pull' ], timeout=60, cwd=self.name)
