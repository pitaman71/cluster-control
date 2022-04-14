import typing
import boto3
import argparse 
import json
import sys

from . import configurable
from . import resource
from . import code_repository
from . import ec2_cloud
from . import package_manager
from . import file
from . import formats

iam_client = boto3.client('iam', 'us-east-1')

class BasicExecutionRole(resource.Resource):
    """Resource representing an agent (IAM role) that has permission execute the lambda function when triggered by an inbound lambda call"""
    lambda_name: configurable.Var[str]

    ec2_iam_role: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)

        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.ec2_iam_role = configurable.Var(self, 'ec2_iam_role')
    
    def up(self, phase: resource.Phase):
        super().up(phase)
        if self.ec2_iam_role:
            print(f"{self} : EC2 instance id is already loaded")
        else:
            with phase.sub(f"creating EC2 IAM role {self}") as phase:
                role_policy = {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                        "Sid": "",
                        "Effect": "Allow",
                        "Principal": {
                            "Service": "lambda.amazonaws.com"
                        },
                        "Action": "sts:AssumeRole"
                        }
                    ]
                }

                response = iam_client.create_role(
                    RoleName=f"{self.lambda_name()}.ExecuteLambdaRole",
                    AssumeRolePolicyDocument=json.dumps(role_policy)
                )
                print(f"DEBUG: iam_client.create_role response is {response}")
                self.ec2_iam_role.select(response['Role']['RoleId'])

    def down(self, phase: resource.Phase):
        if self.ec2_iam_role:
            with phase.sub(f"deleting EC2 IAM role {self}") as phase:
                response = iam_client.delete_role(RoleName=f"{self.lambda_name()}.ExecuteLambdaRole")

class LambdaFunction(resource.Resource):
    lambda_name: configurable.Var[str]

    iam_role: resource.Ref[BasicExecutionRole]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.iam_role = resource.Ref(self, 'iam_role')

    def elaborate(self, phase: resource.Phase):
        self.iam_role.resolve(phase, BasicExecutionRole)
        self.iam_role().alias(lambda_name=self.lambda_name)
        super().elaborate(phase)


parser = argparse.ArgumentParser(description='Spinup cloud cluster')
parser.add_argument('verb', type=str, choices=['create', 'CREATE', 'configure', 'CONFIGURE', 'up', 'UP', 'down', 'DOWN', 'watch', 'WATCH', 'ip', 'IP', 'ssh', 'SSH', 'stop', 'STOP', 'start', 'START', 'pull', 'PULL', 'get', 'GET', 'put', 'PUT', 'build', 'BUILD'],
                    help='command verbs: bring cluster UP, take cluster DOWN, WATCH server logs, show service IP address, open SSH shell on service instance')
parser.add_argument('-c', '--config', type=str, help='path to configuration file', required=True)
args, unknown = parser.parse_known_args()

if args.verb in ('create', 'CREATE'):
    parser.add_argument('resource_name', type=str, help='name of the new resource instance')
    args, unknown = parser.parse_known_args()
    if args.resource_name is None:
        raise RuntimeError(f"Must provide a resource_name when creating a resource")
    config = LambdaFunction([ args.resource_name ])
else:
    with open(args.config, 'rt') as fp:
        as_json = json.load(fp, object_hook=formats.json_as_python_set)
        reader = formats.JSONReader(sys.modules[__name__], as_json)
        config = reader.read()
    if not isinstance(config, resource.Resource):
        raise RuntimeError(f"Config file {args.c} is not a resource, it is a {config}")

all_vars: typing.Set[configurable.Var] = set()
all_resources: typing.Set[resource.Resource] = set()
config.collect(all_vars, all_resources)
for var in all_vars:
    name = '-'.join(var.path()[1:])
    if name == '':
        print(f"DEBUG: malformed {var}")
    else:
        parser.add_argument('--'+name, type=str)

args, unknown = parser.parse_known_args()

for var in all_vars:
    name = '-'.join(var.path()[1:])
    if hasattr(args, name) and getattr(args, name) is not None:
        getattr(config, name).select(getattr(args, name))

persistor = resource.PersistInFile(args.config, config)

if args.verb in ('up', 'UP'):
    with resource.Phase(f'cluster_control UP {config}', persistor, config) as phase:
        config.elaborate(phase)
        config.up(phase)
        
elif args.verb in ('down', 'DOWN'):
    with resource.Phase(f'cluster_control DOWN {config}', persistor, config) as phase:
        config.down(phase)
elif args.verb in ('ssh', 'SSH'):
    if not hasattr(config, 'shell'):
        raise RuntimeError(f'ssh command is not supported for {config}')
    with resource.Phase(f'cluster_control SSH {config}', persistor, config) as phase:
        getattr(config, 'shell')(phase)
elif args.verb in ('watch', 'WATCH'):
    if not hasattr(config, 'watch'):
        raise RuntimeError(f'watch command is not supported for {config}')
    with resource.Phase(f'cluster_control WATCH {config}', persistor, config) as phase:
        getattr(config, 'watch')(phase)
else:
    persistor.save()
