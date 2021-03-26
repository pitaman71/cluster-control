#! env python3

from __future__ import annotations

from typing import List, Dict
import abc

import os
import json
import urllib

import resource
import ssl_security

class GithubDeployKey(resource.Resource):
    """Resource representing an RSA key pair registed with github to enable git repo read access for deployment purposes"""
    def __init__(self, name: str=None, repo_key: ssl_security.RSAKey=None, owner:str=None, repo:str=None):
        self.name = name
        self.repo_key = repo_key
        self.owner = owner
        self.repo = repo
        self.repo_key_id = None

    def url(self):
        return f'git@github.com:{self.owner}/{self.repo}.git'

    def plan(self):
        if self.repo_key is None:
            print(f"{self.__class__.__qualname__}.plan : allocating new deploy key for read access to github repo {self.owner}/{self.repo}")
            self.repo_key = ssl_security.RSAKey(self.name + '.rsa', 2048)
        self.repo_key.plan()

    def up(self, top):
        self.repo_key.up(top)
        if self.repo_key_id is not None:
            print(f"{self.__class__.__qualname__}.up : already registered deploy key for read access to github repo {self.owner}/{self.repo}")
        else:
            print(f"{self.__class__.__qualname__}.up : registering deploy key for read access to github repo {self.owner}/{self.repo}")
            create_key_params = json.dumps({
                #'accept': 'application/vnd.github.v3+json',
                #'owner': self.owner,
                #'repo': self.repo,
                #'title': self.name,
                'key': 'ssh-rsa '+self.repo_key.public_key_data,
                'read_only': True
            }).encode('utf-8')
            authorization = 'token ' + os.environ["GITHUB_PASSWORD"]
            request = urllib.request.Request(
                f'https://api.github.com/repos/{self.owner}/{self.repo}/keys', 
                method='POST', headers={ 'Authorization': authorization })
            with urllib.request.urlopen(request, data=create_key_params) as resp:
                if resp.status >= 300 or resp.status < 200:
                    raise RuntimeError(resp.read().decode('utf-8'))
                else:
                    asJSON = json.load(resp)
                    if 'id' not in asJSON:
                        raise RuntimeError('Malformed response from github did not contain key id: '+json.dumps(asJSON))
                    self.repo_key_id = asJSON['id']
            top.save()

    def down(self, top):
        if self.repo_key_id is not None:
            print(f"{self.__class__.__qualname__}.down : un-registering deploy key for read access to github repo {self.owner}/{self.repo}")
            authorization = 'token ' + os.environ["GITHUB_PASSWORD"]
            request = urllib.request.Request(
                f'https://api.github.com/repos/{self.owner}/{self.repo}/keys/{self.repo_key_id}', 
                method='DELETE',
                headers={ 'Authorization': authorization
            })
            with urllib.request.urlopen(request) as resp:
                if resp.status >= 300 or resp.status < 200:
                    raise RuntimeError(resp.read().decode('utf-8'))
                else:
                    self.repo_key_id = None
                    top.save()
        self.repo_key.down(top)

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('repo_key')
        visitor.inline('owner')
        visitor.inline('repo')
        visitor.inline('repo_key_id')
        visitor.endObject(self)

class GitDeploy(resource.Resource):
    """Resource representing deployment of code from git as a clone on an instance"""
    def __init__(self, name: str=None, instance: resource.Instance=None, deploy_key: GithubDeployKey=None, owner:str=None, repo:str=None):
        self.name = name
        self.instance = instance
        self.deploy_key = deploy_key
        self.owner = owner
        self.repo = repo
        self.is_installed = False

    def url(self):
        return f'git@github.com:{self.owner}/{self.repo}.git'

    def plan(self):
        pass

    def up(self, top):
        if self.is_installed:
            print(f"{self.__class__.__qualname__}.up : git deployment {self.instance.name}:{self.name} of {self.repo}/{self.owner} already exists")
        else:
            print(f"{self.__class__.__qualname__}.up : git deployment  {self.instance.name}:{self.name} installing deploy key {self.deploy_key.name}")
            repo_key_remote_path = self.name+'.pvt-repo-key.pem'
            self.instance.put(self.deploy_key.repo_key.get_private_key_file(), repo_key_remote_path, 60, chmod='0600')
            self.instance.execute(['ssh-add', repo_key_remote_path ], 60)

            print(f"{self.__class__.__qualname__}.up : git deployment  {self.instance.name}:{self.name} of {self.repo}/{self.owner} cloning")
            self.instance.execute(['rm', '-f', self.name ], 60)
            self.instance.execute(['git', 'config', '--global', 'core.sshCommand', """'ssh -o UserKnownHostsFile=/dev/null -o StrictHostKeyChecking=no'"""], 60)
            self.instance.execute(['git', 'clone', self.url(), self.name], 60)
            self.is_installed = True
            top.save()

    def down(self, top):
        if self.is_installed:
            print(f"{self.__class__.__qualname__}.down : git deployment {self.instance.name}:{self.name} deleting clone")
            self.instance.execute(['sudo', 'rm', '-rf', self.name ], 60)
            self.is_installed = False
            top.save()

    def pull(self):
        if self.is_installed:
            repo_key_remote_path = self.name+'.pvt-repo-key.pem'
            self.instance.put(self.deploy_key.repo_key.get_private_key_file(), repo_key_remote_path, 60, chmod='0600')
            self.instance.execute(['ssh-add', repo_key_remote_path ], 60)
            self.instance.execute(['git', 'remote', 'show', 'origin' ], timeout=60, cwd=self.name)
            self.instance.execute(['git', 'pull' ], timeout=60, cwd=self.name)

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('name')
        visitor.inline('instance')
        visitor.inline('deploy_key')
        visitor.inline('owner')
        visitor.inline('repo')
        visitor.inline('is_installed')
        visitor.endObject(self)
