#! env python3

from __future__ import annotations

from typing import List, Dict
import abc

import json
import os
import sys

import resource
import blob
import formats
import package_manager
import ssl_security
import ec2_cloud
import code_repository

script_path = os.path.dirname(os.path.abspath(__file__))
repo_path = script_path.split('/')
repo_path = repo_path[0:len(repo_path)-1]
repo_path = '/'.join(repo_path)

class Configuration(resource.Resource):
    """Resource representing top-level configuration of all cloud resources necessary to run the API service
    and all of the static and on-demand resources on which it depends."""
    def __init__(self):
        self.cluster_name = 'cluster3'
        self.repo_name = 'craftsmanexchange'
        self.file_name = 'cluster_config.json'
        self.git_deploy_key = None
        self.instance_access_key = None
        self.ec2_instance_type = 't2.micro'
        self.security_group = None
        self.public_ip = None
        self.cluster = None
        self.yum_package_names = ['']
        self.yum_package_loaders = None
        self.git_cloners = None
        self.master_config_files = None
        self.https_creds_files = None
        self.api_services = None
        #self.local_trust_dev_creds = None

    def save(self):
        next_file_name = f"{self.file_name}.next"
        with open(next_file_name, 'wt') as fp:
            writer = formats.JSONWriter(sys.modules[__name__], self)
            self.marshal(writer)
            fp.write(json.dumps(writer.write()))
        os.rename(next_file_name, self.file_name)

    def load(self):
        if os.path.exists(self.file_name):
            with open(self.file_name, 'rt') as fp:    
                reader = formats.JSONReader(sys.modules[__name__], json.load(fp))
                self.marshal(reader)

    def plan(self):
        if self.git_deploy_key is None:
            self.git_deploy_key = code_repository.GithubDeployKey(f'{self.repo_name}-{self.cluster_name}-deploy-key', owner='pitaman71', repo=self.repo_name)
        self.git_deploy_key.plan()

        if self.instance_access_key is None:
            self.instance_access_key = ec2_cloud.KeyPair(f'{self.repo_name}-{self.cluster_name}-api-admin')
        self.instance_access_key.plan()

        if self.security_group is None:
            self.security_group = ec2_cloud.SecurityGroup(f'{self.repo_name}-{self.cluster_name}-api-sg', 'API instance security group')
        self.security_group.plan()

        if self.public_ip is None:
            self.public_ip = ec2_cloud.PublicIp(f'{self.repo_name}-{self.cluster_name}-api-ip')
        self.public_ip.plan()

        if self.cluster is None:
            self.cluster = ec2_cloud.Cluster(f'{self.repo_name}-{self.cluster_name}-api', self.ec2_instance_type, 'ami-02354e95b39ca8dec', self.instance_access_key, self.security_group, self.public_ip)
        self.cluster.plan()

        if self.yum_package_loaders is None:
            self.yum_package_loaders = [ 
                package_manager.YumPackageLoader(instance, { 'node10': 'https://rpm.nodesource.com/setup_10.x' }, ['nodejs']) for instance in self.cluster.instances
            ] + [
                package_manager.YumPackageLoader(instance, {  }, ['git']) for instance in self.cluster.instances
            ]
        for yum_package_loader in self.yum_package_loaders: yum_package_loader.plan()

        if self.git_cloners is None:
            self.git_cloners = [
                code_repository.GitDeploy(self.repo_name, instance, self.git_deploy_key, 'pitaman71', self.repo_name) for instance in self.cluster.instances
            ]
        for git_cloner in self.git_cloners: git_cloner.plan()

        if self.master_config_files is None:
            self.master_config_files = [
                blob.File.Put('master_config_file','json', f'file:/Users/pitaman/Documents/sand/{self.repo_name}/express-api/src/config.json', instance, f'{self.repo_name}/express-api/src/config.json')
                for instance in self.cluster.instances
            ]
        for master_config_file in self.master_config_files: master_config_file.plan()

        if self.https_creds_files is None:
            self.https_creds_files = [
                blob.File.Put('server','cert', f'file:{repo_path}/cert/{self.cluster_name}.cert', instance, f'{self.repo_name}/express-api/server.cert')
                for instance in self.cluster.instances
            ] + [
                blob.File.Put('server','key', f'file:{repo_path}/cert/{self.cluster_name}.key', instance, f'{self.repo_name}/express-api/server.key')
                for instance in self.cluster.instances
            ]
        for https_creds_file in self.https_creds_files: https_creds_file.plan()

        if self.api_services is None:
            self.api_services = [
                ec2_cloud.Service('auction_control_service', 'Auction Control Service', instance, [
                    f'cd /home/ec2-user/{self.repo_name}/data-model',
                    'npm i',
                    'npm run-script build',
                    f'cd /home/ec2-user/{self.repo_name}/express-api',
                    'npm i',
                    'npm run-script link',
                    'npm start'
                ]) for instance in self.cluster.instances
            ]
        for api_service in self.api_services: api_service.plan()
        
    def order_of_operations(self):
        return [
            self.git_deploy_key,
            self.instance_access_key,
            self.security_group,
            self.public_ip,
            self.cluster
        ] + self.yum_package_loaders + self.git_cloners + self.master_config_files + self.https_creds_files + self.api_services

    def watch(self):
        self.api_services[0].watch()

    def ip(self):
        self.api_services[0].ip()

    def ssh(self):
        self.api_services[0].ssh()

    def stop(self):
        self.api_services[0].stop()

    def start(self):
        self.api_services[0].start()

    def pull(self):
        for git_cloner in self.git_cloners:
            git_cloner.pull()

    def build(self):
        for instance in self.cluster.instances:
            instance.execute(['sudo', 'npm', 'run', 'build'], timeout=None, cwd=f'{self.repo_name}/data-model')

    def get(self, remote_path:str, local_path: str):
        self.cluster.instances[0].get(remote_path, local_path, 60)

    def put(self, local_path: str, remote_path:str):
        self.cluster.instances[0].put(local_path, remote_path, 60)

    def marshal(self, visitor):
        visitor.beginObject(self)
        visitor.inline('git_deploy_key')
        visitor.inline('instance_access_key')
        visitor.inline('security_group')
        visitor.inline('public_ip')
        visitor.inline('cluster')
        visitor.inline('yum_package_loaders')
        visitor.inline('git_cloners')
        visitor.inline('master_config_files')
        visitor.inline('https_creds_files')
        visitor.inline('api_services')
        visitor.endObject(self)

import argparse

parser = argparse.ArgumentParser(description='Spinup cloud cluster')
parser.add_argument('verb', type=str, choices=['up', 'UP', 'down', 'DOWN', 'watch', 'WATCH', 'ip', 'IP', 'ssh', 'SSH', 'stop', 'STOP', 'start', 'START', 'pull', 'PULL', 'get', 'GET', 'put', 'PUT', 'build', 'BUILD'],
                    help='command verbs: bring cluster UP, take cluster DOWN, WATCH server logs, show service IP address, open SSH shell on service instance')
args, unknown = parser.parse_known_args()

config = Configuration()
config.load()
config.plan()
if args.verb in ('up', 'UP'):
    config.up(config)
elif args.verb in ('down', 'DOWN'):
    config.down(config)
elif args.verb in ('watch', 'WATCH'):
    config.watch()
elif args.verb in ('ip', 'IP'):
    config.ip()
elif args.verb in ('ssh', 'SSH'):
    config.ssh()
elif args.verb in ('stop', 'STOP'):
    config.stop()
elif args.verb in ('start', 'START'):
    config.start()
elif args.verb in ('pull', 'PULL'):
    config.pull()
elif args.verb in ('build', 'BUILD'):
    config.build()
elif args.verb in ('get', 'GET'):
    parser = argparse.ArgumentParser(description='GET file from instance')
    parser.add_argument('remote_path', type=str)
    parser.add_argument('local_path', type=str)
    verb_args = parser.parse_args(unknown)
    config.get(verb_args.remote_path, verb_args.local_path)
elif args.verb in ('put', 'PUT'):
    parser = argparse.ArgumentParser(description='PUT file to instance')
    parser.add_argument('local_path', type=str)
    parser.add_argument('remote_path', type=str)
    verb_args = parser.parse_args(unknown)
    config.put(verb_args.local_path, verb_args.remote_path)
    
config.save()
