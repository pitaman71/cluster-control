#! env python3

from __future__ import annotations

import typing
import io

import boto3
import secrets
import sys
import os
import stat
import time
import subprocess
import tempfile

from . import actions
from . import configurable
from . import resource
from . import file

ec2 = boto3.resource('ec2', 'us-east-1')
ec2_client = boto3.client('ec2', 'us-east-1')

class KeyPair(resource.Resource):
    """Resource representing an RSA key pair generated by EC2 and used to access instances"""
    private: resource.Ref[file.Image]
    ec2_name: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.private = resource.Ref(self, 'private')
        name = 'cluster-keypair' if resource_path is None else '-'.join(resource_path)
        self.ec2_name = configurable.Var(self, 'ec2_name', name)

    def elaborate(self, phase: resource.Phase):
        self.private.resolve(phase, file.Image)
        super().elaborate(phase)

    def up(self, phase: resource.Phase): 
        super().up(phase)
        if self.private().contents:
            print(f"{self} : reusing private key")
        else:
            print(f"{self} : creating a new key")
            key_pair = ec2.create_key_pair(KeyName=self.ec2_name())
            self.private().load(key_pair.key_material)

    def down(self, phase: resource.Phase):
        ec2_client.delete_key_pair(KeyName=self.ec2_name())
        if self.private:
            self.private().clear()

class SecurityGroup(resource.Resource):
    """Resource representing TCP/IP inbound/outbound port security rules applied to a group of instances"""
    description: configurable.Var[str]
    ec2_name: configurable.Var[str]
    ec2_security_group_id: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.description = configurable.Var(self, 'description')
        name = 'cluster-sg' if resource_path is None else '-'.join(resource_path)
        self.ec2_name = configurable.Var(self, 'ec2_name', name)
        self.ec2_security_group_id = configurable.Var(self, 'ec2_security_group_id')
    
    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.ec2_security_group_id:
            print(f"{self} : EC2 security group is already allocated")
        elif not self.description:
            print(f"{self} : description is not selected")            
        else:
            print(f"{self} : creating a new security group")
            ec2_security_group = ec2.create_security_group(GroupName=self.ec2_name(), Description=self.description())
            self.ec2_security_group_id.select(ec2_security_group.id)
            ip_permissions = [{
                'IpProtocol': 'tcp', 'FromPort': 3001, 'ToPort': 3001,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }]
            ip_permissions.append({
                # SSH ingress open to only the specified IP address
                'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            })
            ec2_security_group.authorize_ingress(IpPermissions=ip_permissions)

    def down(self, phase: resource.Phase):
        if self.ec2_security_group_id:
            print(f"{self} : deleting security group on EC2")
            security_group = ec2.SecurityGroup(self.ec2_security_group_id())
            security_group.delete()
            self.ec2_security_group_id.clear()

class PublicIp(resource.Resource):
    """Resource representing an allocated public IP address that can be associated with an instance"""
    ec2_name: configurable.Var[str]
    ec2_allocation_id: configurable.Var[str]
    ip_address: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        name = 'cluster-ip' if resource_path is None else '-'.join(resource_path)
        self.ec2_name = configurable.Var(self, 'ec2_name', name)
        self.ec2_allocation_id = configurable.Var(self, 'ec2_allocation_id')
        self.ip_address = configurable.Var(self, 'ip_address')

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.ec2_allocation_id and self.ip_address:
            print(f"{self} : EC2 public IP is already allocated")
        else:
            print(f"{self} : creating a new public IP")
            response = ec2.meta.client.allocate_address()
            # !! cannot do? response.create_tags(Tags=[{ 'Key': 'Name', 'Value': self.name }])
            self.ec2_allocation_id.select(response['AllocationId'])
            self.ip_address.select(response['PublicIp'])

    def down(self, phase: resource.Phase):
        if self.ec2_allocation_id:
            print(f"{self} : releasing EC2 public IP")
            ec2.meta.client.release_address(AllocationId=self.ec2_allocation_id())
            self.ec2_allocation_id.clear()            
        self.ip_address.clear()

class Service(resource.Resource):
    """Resource representing a Systemd service definition which calls commands we provide"""
    description: configurable.Var[str]
    commands: configurable.Var[typing.List[str]]
    is_loaded: configurable.Var[bool]

    instance: resource.Ref[Instance]
    service_config: resource.Ref[file.Transfer]
    entry_script: resource.Ref[file.Transfer]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.description = configurable.Var(self, 'description')
        self.commands = configurable.Var(self, 'commands')
        self.is_loaded = configurable.Var(self, 'is_loaded')

        self.instance = resource.Ref(self, 'instance')
        self.service_config = resource.Ref(self, 'service_config')
        self.entry_script = resource.Ref(self, 'entry_script')

    def elaborate(self, phase: resource.Phase):
        if not self.service_config:
            self.service_config.resolve(phase, file.Transfer)
            self.service_config().alias(
                remote=file.RemoteFile([ *(self.path()), 'service-config-remote' ]).alias(
                    remote_path=f"/etc/systemd/system/{self.name}.service",
                    instance=self.instance,
                    sudo=True,
                    chmod='664'
                )
            )
        if not self.entry_script:
            self.entry_script.resolve(phase, file.Transfer)
            self.entry_script().alias(
                remote=file.RemoteFile([ *(self.path()), 'entry-script-remote' ]).alias(
                    remote_path=f"/home/ec2-user/{self.name}.sh",
                    instance=self.instance,
                    sudo=True,
                    chmod='775'
                )
            )
        super().elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.is_loaded and self.is_loaded():
            print(f"{self} : service is already defined on instance {self.instance}")
        else:
            print(f"{self} : registering service on instance {self.instance}")
            self.service_config().image().load(f"""
[Unit]
Description={self.description}

[Service]	
ExecStart=/usr/bin/bash -c /home/ec2-user/{self.name}.sh

[Install]
WantedBy=default.target""".strip())
            self.service_config().put()

            self.entry_script().image().load('\n'.join([ '#env bash' ] + self.commands()).strip())
            self.entry_script().put()
            self.instance().execute(['sudo', 'systemctl', 'daemon-reload'], 60)
            self.instance().execute(['sudo', 'systemctl', 'start', f"{self.name}.service"], 60)
            self.is_loaded.select(True)

    def down(self, phase: resource.Phase):
        if self.is_loaded and self.is_loaded():
            print(f"{self} : un-registering service on instance {self.instance().name}")
            self.instance().execute(['sudo', 'systemctl', 'stop', f"{self.name}.service"], 60)
            self.instance().execute(['sudo', 'rm', '-f', f"/etc/systemd/system/{self.name}.service"], 60)
            self.instance().execute(['sudo', 'systemctl', 'daemon-reload'], 60)
            self.is_loaded.select(False)

    def watch(self):
        instance = self.instance()
        if self.name is None:
            raise RuntimeError('name must be configured first!')
        instance.execute(['sudo', 'journalctl', '-f', '-u', self.name], timeout=None)

    def stop(self):
        if self.is_loaded and self.is_loaded():
            instance = self.instance()
            instance.execute(['sudo', 'systemctl', 'stop', f"{self.name}.service"], 60)

    def start(self):
        if self.is_loaded and self.is_loaded():
            instance = self.instance()
            instance.execute(['sudo', 'systemctl', 'start', f"{self.name}.service"], 60)

    
class Instance(resource.Resource):
    """Resource representing a virtual host in the on-demand AWS EC2 cloud"""
    local_key_file: None|str

    instance_type: configurable.Var[str]
    image: configurable.Var[str] 
    root_user_name: configurable.Var[str] 

    key_pair: resource.Ref[KeyPair]
    security_group: resource.Ref[SecurityGroup]
    public_ip: resource.Ref[PublicIp]

    ec2_instance_id: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.local_key_file = None

        self.instance_type = configurable.Var(self, 'instance_type')
        self.image = configurable.Var(self, 'image')
        self.root_user_name = configurable.Var(self, 'root_user_name')
        
        self.key_pair = resource.Ref(self, 'key_pair')
        self.security_group = resource.Ref(self, 'security_group')
        self.public_ip = resource.Ref(self, 'public_ip')

        self.ec2_instance_id = configurable.Var(self, 'ec2_instance_id')

    def target(self):
        result = self.root_user_name()
        if self.public_ip and self.public_ip().ip_address():
            result = result + '@'+ self.public_ip().ip_address()
        return result

    def wait_for_status(self, expected):
        tries = 0
        while tries < 10:
            instance = ec2.Instance(self.ec2_instance_id())
            status = instance.state['Name']
            if status == expected:
                break
            print(f'Waiting 5 more seconds for {self.name} with EC2 Instance ID {self.ec2_instance_id()} has status {status}')
            time.sleep(10)
            tries += 1

        if tries == 10:
            raise RuntimeError(f'Instance did not reach a running state in {tries} attempts')

    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.ec2_instance_id:
            print(f"{self} : EC2 instance id is already loaded")
        else:
            with phase.sub(f"creating EC2 instance in security group {self.security_group()} with key pair {self.key_pair()}") as phase:
                ec2_instances = ec2.create_instances(ImageId=self.image(), InstanceType=self.instance_type(), KeyName=self.key_pair().ec2_name(), SubnetId='subnet-00b393af9a75c85a2', MinCount=1, MaxCount=1, SecurityGroupIds=[self.security_group().ec2_security_group_id()])
                time.sleep(1)
                ec2_instances[0].create_tags(Tags=[{ 'Key': 'Name', 'Value': self.name }])
                self.ec2_instance_id.select(ec2_instances[0].id)
                time.sleep(10)

        # wait for the instance to reach running state
        self.wait_for_status('running')

        # associate the public IP
        with phase.sub(f"associating elastic IP address {self.public_ip().ec2_allocation_id()} as public IP") as phase:
            elastic_ip = ec2.VpcAddress(self.public_ip().ec2_allocation_id())
            elastic_ip.associate(InstanceId=self.ec2_instance_id())

        # wait for the instance to accept SSH connections and commands
        tries = 0
        while tries < 10:
            try:
                self.test()
                break
            except Exception as e:
                print(str(e))
                print(f'Waiting 5 more seconds for {self.name} with EC2 Instance ID {self.ec2_instance_id} to accept SSH connections and commands')
                time.sleep(10)
                tries += 1

        if tries == 10:
            raise RuntimeError(f'Instance did not accept SSH connections and commands after {tries} attempts')

    def down(self, phase: resource.Phase):
        if self.ec2_instance_id:
            print(f"{self} : deleting EC2 instance {self.ec2_instance_id()}")
            instance = ec2.Instance(self.ec2_instance_id())
            instance.terminate()

            # wait for the instance to reach running state
            self.wait_for_status('terminated')
            self.ec2_instance_id.clear()

    def get_local_key_filename(self):
        if self.local_key_file is None:
            with tempfile.NamedTemporaryFile('wb+', delete=False) as keyfile:
                self.local_key_file = keyfile.name
                keyfile.close()
        return self.local_key_file

    def test(self):        
        args=['echo', 'hello world']
        timeout=5
        with open(self.get_local_key_filename(), 'wb+') as keyfile:
            keyfile.write(self.key_pair().private().contents())
            keyfile.close()
            os.chmod(keyfile.name, stat.S_IREAD | stat.S_IWRITE)
            time.sleep(1)
            process = subprocess.Popen(['ssh', '-A', '-o', 'StrictHostKeyChecking=no', '-o', 'ForwardAgent=yes', '-i', keyfile.name, self.target() ] + args, stdin=None, stdout=sys.stdout, stderr=sys.stderr)
            while process.returncode is None:
                try:
                    print("DEBUG: BEGIN calling process.communicate")
                    process.communicate(timeout=timeout)
                    print("DEBUG: END   calling process.communicate")
                except subprocess.TimeoutExpired as e:
                    if process.returncode is not None:
                        raise e
            if process.returncode != 0:
                print(f"DEBUG: FAIL process.returncode = {process.returncode}")
                raise RuntimeError(f'Cannot connect over SSH to {self.name} rc={process.returncode}')

    def shell(self):
        with open(self.get_local_key_filename(), 'wb+') as keyfile:
            keyfile.write(self.key_pair().private().contents())
            keyfile.close()
            os.chmod(keyfile.name, stat.S_IREAD | stat.S_IWRITE)
            time.sleep(1)
            remote_args = ['ssh', '-A', '-o', 'StrictHostKeyChecking=no', '-o', 'ForwardAgent=yes', '-i', keyfile.name, self.target() ]
            print(f"EXEC({self.name}) "+' '.join(remote_args))
            process = subprocess.Popen(remote_args, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr)
            while process.returncode is None:
                try:
                    process.communicate(timeout=1)
                except subprocess.TimeoutExpired:
                    pass
            if process.returncode != 0:
                raise RuntimeError(f'EXEC FAILED with rc={process.returncode}')

    def execute(self, args: typing.List[str], timeout: float|None, stdin:None|bytes|str=None, cwd=None):
        with open(self.get_local_key_filename(), 'wb+') as keyfile:
            keyfile.write(self.key_pair().private().contents())
            keyfile.close()
            os.chmod(keyfile.name, stat.S_IREAD | stat.S_IWRITE)
            time.sleep(1)
            chdir_args = [ 'cd', cwd, '&&' ] if cwd is not None else []
            remote_args = ['ssh', '-A', '-T', '-o', 'StrictHostKeyChecking=no', '-o', 'ForwardAgent=yes', '-i', keyfile.name, self.target() ] + chdir_args + args
            print(f"EXEC({self.name}) "+' '.join(remote_args))
            process = subprocess.Popen(remote_args, stdin=subprocess.PIPE, stdout=sys.stdout, stderr=sys.stderr, shell=False)
            if type(stdin) is bytes:
                input=stdin
            elif type(stdin) is str:
                input=stdin.encode('utf-8')
            else:
                input = None
            if timeout is None:
                while process.returncode is None:
                    try:
                        process.communicate(timeout=1, input=input)
                        input=None
                    except subprocess.TimeoutExpired:
                        pass
            else:
                process.communicate(timeout=timeout, input=input)
            if process.returncode != 0:
                raise RuntimeError(f'EXEC FAILED with rc={process.returncode}')

    def get(self, remote: file.RemoteFile, dest: file.Image, timeout: int):
        with open(self.get_local_key_filename(), 'wb+') as keyfile:
            keyfile.write(self.key_pair().private().contents())
            keyfile.close()
            os.chmod(keyfile.name, stat.S_IREAD | stat.S_IWRITE)
            with tempfile.NamedTemporaryFile('wt+', delete=False) as payload:
                args = [ self.target() + ':' + remote.remote_path(), payload.name ]
                process = subprocess.Popen(['scp', '-o', 'StrictHostKeyChecking=no', '-o', 'ForwardAgent=yes', '-i', keyfile.name ] + args, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                (stdout, stderr) = process.communicate(timeout=timeout)
                print(stdout.decode('utf-8') + stderr.decode('utf-8'))
                with open(payload.name, 'rb') as payload_:
                    dest.contents.select(payload_.read())
                time.sleep(1)
                os.unlink(payload.name)

    def put(self, src: file.Image, remote: file.RemoteFile, timeout:int):
        with open(self.get_local_key_filename(), 'wb+') as keyfile:
            keyfile.write(self.key_pair().private().contents())
            keyfile.close()
            os.chmod(keyfile.name, stat.S_IREAD | stat.S_IWRITE)
            time.sleep(1)
            with tempfile.NamedTemporaryFile('wb+', delete=False) as payload:
                payload.write(src.contents())
                payload.close()
                time.sleep(1)
                if remote.sudo and remote.sudo():
                    tmp_path = secrets.token_urlsafe(10)
                    args = [ payload.name, self.target() + ':' + tmp_path ]
                else:
                    tmp_path = None
                    args = [ payload.name, self.target() + ':' + remote.remote_path() ]

                process = subprocess.Popen(['scp', '-o', 'StrictHostKeyChecking=no', '-o', 'ForwardAgent=yes', '-i', keyfile.name ] + args, stdin=None, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                (stdout, stderr) = process.communicate(timeout=timeout)
                print(stdout.decode('utf-8') + stderr.decode('utf-8'))

                if remote.sudo and remote.sudo() and tmp_path:
                    self.execute(['sudo', 'mv', '-f', tmp_path, remote.remote_path() ], 60)

                if remote.chmod:
                    self.execute((['sudo'] if remote.sudo() else []) + ['chmod', remote.chmod(), remote.remote_path() ], 60)
                os.unlink(payload.name)

    def delete(self, remote: file.RemoteFile, timeout: int):
        self.execute([ 'rm', '-f', remote.remote_path() ], timeout)

class Cluster(resource.Resource):
    """Resource representing a virtual cluster in the on-demand AWS EC2 cloud"""
    instance_type: configurable.Var[str]
    image: configurable.Var[str] 
    root_user_name: configurable.Var[str] 
    count: configurable.Var[int]

    key_pair: resource.Ref[KeyPair]
    security_group: resource.Ref[SecurityGroup]
    public_ip: resource.Ref[PublicIp]
    instances: typing.List[Instance]

    def __init__(self, resource_path: None|typing.List[str] = None):
        super().__init__(resource_path)
        self.instance_type = configurable.Var(self, 'instance_type')
        self.image = configurable.Var(self, 'image')
        self.root_user_name = configurable.Var(self, 'root_user_name')
        self.count = configurable.Var(self, 'count')

        self.key_pair = resource.Ref(self, 'key_pair')
        self.security_group = resource.Ref(self, 'security_group')
        self.public_ip = resource.Ref(self, 'public_ip')
        self.instances = []

    def elaborate(self, phase: resource.Phase):
        self.key_pair.resolve(phase, KeyPair)

        self.security_group.resolve(phase, SecurityGroup)
        self.security_group().alias(description=f"{self.name}-sg")

        self.public_ip.resolve(phase, PublicIp)

        super().elaborate(phase)

        if len(self.instances) > 0:
            print(f"SKIP {self} {len(self.instances)} instances have already been created")
        else:
            with phase.sub(f"{self} : creating {self.count()} ec2 instances"):
                for i in range(int(self.count())):
                    instance_name = f"instance#{i}"
                    with phase.sub(f"{self} : creating ec2 instance {instance_name}"):
                        instance = Instance([ *(self.path()), instance_name ]).alias(
                            instance_type = self.instance_type,
                            image = self.image,
                            root_user_name = self.root_user_name,
                            key_pair = self.key_pair,
                            security_group = self.security_group
                        )
                        if i == 0:
                            instance.alias(public_ip=self.public_ip)
                        self.instances.append(instance)
                for instance in self.instances:
                    with phase.sub(f"ELABORATE {instance}") as phase:
                        instance.elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        for instance in self.instances:
            with phase.sub(f"UP {instance}") as phase:
                instance.up(phase)

    def down(self, phase: resource.Phase):
        for instance in self.instances:
            with phase.sub(f"DOWN {instance}") as phase:
                instance.down(phase)
        super().down(phase)

    def shell(self, phase: resource.Phase):
        self.instances[0].shell()

    def marshal(self, visitor):
        super().marshal(visitor, lambda visitor: visitor.inline('instances'))

the: Cluster|None = None

if __name__ == "__main__":
    from . import main
    controller = main.Controller([ 
        actions.Do[Cluster](['up'], lambda resource, phase: (resource.elaborate(phase), resource.up(phase))),
        actions.Do[Cluster](['down'], lambda resource, phase: resource.down(phase)),
        actions.Do[Cluster](['shell'], lambda resource, phase: resource.shell(phase)),
    ] )
    controller()
