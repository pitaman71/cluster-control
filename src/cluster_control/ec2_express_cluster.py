import typing
from xmlrpc.client import boolean

from . import configurable
from . import resource
from . import code_repository
from . import ec2_cloud
from . import package_manager
from . import file

class ManageInstance(resource.Resource):
    repo_owner: configurable.Var[str]
    repo_name: configurable.Var[str]
    server_certs_path: configurable.Var[str]

    deploy_key: resource.Ref[code_repository.GithubDeployKey]
    instance: resource.Ref[ec2_cloud.Instance]

    yum_install_node: resource.Ref[package_manager.YumPackageLoader]
    yum_install_git: resource.Ref[package_manager.YumPackageLoader]
    git_deploy_code: resource.Ref[code_repository.GitDeploy]
    install_server_cert: resource.Ref[file.Transfer]
    install_server_key: resource.Ref[file.Transfer]
    setup_express_service: resource.Ref[ec2_cloud.Service]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.repo_owner = configurable.Var(self, 'repo_owner')
        self.repo_name = configurable.Var(self, 'repo_name')
        self.server_certs_path = configurable.Var(self, 'server_certs_path')

        self.deploy_key = resource.Ref(self, 'deploy_key')
        self.instance = resource.Ref(self, 'instance', ec2_cloud.Instance)

        self.yum_install_node = resource.Ref(self, 'yum_install_node', package_manager.YumPackageLoader)
        self.yum_install_git = resource.Ref(self, 'yum_install_git', package_manager.YumPackageLoader)
        self.git_deploy_code = resource.Ref(self, 'git_deploy_code', code_repository.GitDeploy)
        self.install_server_cert = resource.Ref(self, 'install_server_cert', file.Transfer)
        self.install_server_key = resource.Ref(self, 'install_server_key', file.Transfer)
        self.setup_express_service = resource.Ref(self, 'setup_express_service', ec2_cloud.Service)

    def elaborate(self, phase: resource.Phase):
        self.yum_install_node().alias(
            instance=self.instance,
            yum_repos = { 'node14': 'https://rpm.nodesource.com/setup_14.x' }, 
            package_names = ['nodejs']
        ) 

        self.yum_install_git().alias(
            instance=self.instance, 
            yum_repos = {  }, 
            package_names = ['git']
        )

        self.git_deploy_code().alias(
            instance=self.instance,
            deploy_key=self.deploy_key,
            repo=self.repo_name,
            owner=self.repo_owner)

        self.install_server_cert().alias(
            local=file.LocalFile([ *(self.path()), 'server-cert-source' ]).alias(
                local_path=f"{self.server_certs_path()}/cert/ssl.cert"
            ),
            remote=file.RemoteFile([ *(self.path()), 'server-cert-dest' ]).alias(
                instance=self.instance,
                remote_path=f'{self.repo_name}/express-api/server.cert'
            )
        )

        self.install_server_key().alias(
            local=file.LocalFile([ *(self.path()), 'server-key-source' ]).alias(
                local_path=f"{self.server_certs_path()}/cert/ssl.key"
            ),
            remote=file.RemoteFile([ *(self.path()), 'server-key-dest' ]).alias(
                instance=self.instance,
                remote_path=f'{self.repo_name}/express-api/server.key'
            )
        )

        self.setup_express_service().alias(
            instance=self.instance, 
            commands=[
                f'cd /home/ec2-user/{self.repo_name}/data-model',
                'npm i',
                'npm run-script build',
                f'cd /home/ec2-user/{self.repo_name}/express-api',
                'npm i',
                'npm run-script link',
                'npm start'
            ]
        )
        super().elaborate(phase)

    def up(self, phase: resource.Phase):        
        super().up(phase)
        self.install_server_cert().put()
        self.install_server_key().put()
        self.instance().execute(['sudo', 'npm', 'run', 'build'], timeout=None, cwd=f'{self.repo_name}/data-model')

    def down(self, phase: resource.Phase):
        self.install_server_cert().delete()
        self.install_server_key().delete()

    def pull(self, phase: resource.Phase):
        self.git_deploy_code().pull(phase)

class ManageCluster(resource.Resource):
    """Resource representing top-level configuration of all cloud resources necessary to run the API service
    and all of the static and on-demand resources on which it depends."""
    repo_owner: configurable.Var[str]
    repo_name: configurable.Var[str]
    ec2_instance_type: configurable.Var[str]
    instance_count: configurable.Var[int]
    server_certs_path: configurable.Var[str]

    deploy_key: resource.Ref[code_repository.GithubDeployKey]
    key_pair: resource.Ref[ec2_cloud.KeyPair]
    security_group: resource.Ref[ec2_cloud.SecurityGroup]
    public_ip: resource.Ref[ec2_cloud.PublicIp]
    cluster: resource.Ref[ec2_cloud.Cluster]

    instances: typing.List[resource.Ref[ManageInstance]]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        # config properties
        self.repo_owner = configurable.Var(self, 'repo_owner')
        self.repo_name = configurable.Var(self, 'repo_name')
        self.ec2_instance_type = configurable.Var(self, 'ec2_instance_type', 't2.micro')
        self.instance_count = configurable.Var(self, 'instance_count', 1)
        self.server_certs_path = configurable.Var(self, 'server_certs_path')

        # child resources
        self.deploy_key = resource.Ref(self, 'deploy_key', code_repository.GithubDeployKey)
        self.key_pair = resource.Ref(self, 'key_pair', ec2_cloud.KeyPair)
        self.security_group = resource.Ref(self, 'security_group', ec2_cloud.SecurityGroup)
        self.public_ip = resource.Ref(self, 'public_ip', ec2_cloud.PublicIp)
        self.cluster = resource.Ref(self, 'cluster', ec2_cloud.Cluster)
        self.instances = []

    def elaborate(self, phase: resource.Phase):
        self.deploy_key().alias(owner=self.repo_owner, repo=self.repo_name)
        self.security_group().alias(description=f"{self.name}-sg")
        self.cluster().alias(
            count=self.instance_count,
            instance_type=self.ec2_instance_type,
            image='ami-02354e95b39ca8dec',
            key_pair=self.key_pair,
            security_group=self.security_group,
            public_ip=self.public_ip
        )
        super().elaborate(phase)
        added: typing.List[ManageInstance] = []
        for index in range(0, len(self.cluster().instances)):
            if len(self.instances) <= index:
                name = str(len(self.instances))
                instance = ManageInstance([ *self.path(), name]).alias(
                    repo_owner = self.repo_owner,
                    repo_name = self.repo_name,
                    server_certs_path = self.server_certs_path,
                    instance = self.cluster().instances[index],
                    deploy_key = self.deploy_key
                )
                self.instances.append(resource.Ref(self, name).use(instance))
                added.append(instance)
        for instance in added:
            instance.validate(phase)
            instance.elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        for instance in self.instances:
            with phase.sub(f"UP {instance()}") as phase:
                instance().up(phase)
        
    def down(self, phase: resource.Phase):
        for instance in self.instances:
            with phase.sub(f"DOWN {instance()}") as phase:
                instance().down(phase)
        super().down(phase)