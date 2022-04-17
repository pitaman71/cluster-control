import typing
import boto3
import argparse 
import json
import sys
import shutil
import time
import tempfile
import uuid

from . import configurable
from . import resource
from . import code_repository
from . import aws_ec2
from . import package_manager
from . import file
from . import formats

iam_client = boto3.client('iam', 'us-east-1')
lambda_client = boto3.client('lambda', 'us-east-1')
api_client = boto3.client('apigateway', 'us-east-1')

class ExecutionRole(resource.Resource):
    """Resource representing an agent (IAM role) that has permission execute the lambda function when triggered by an inbound lambda call"""
    lambda_name: configurable.Var[str]

    iam_role_id: configurable.Var[str]
    iam_role_arn: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)

        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.iam_role_id = configurable.Var(self, 'iam_role_id')
        self.iam_role_arn = configurable.Var(self, 'iam_role_arn')
    
    def get_role_name(self):
        return f"{self.lambda_name()}.ExecuteLambdaRole"

    def get_role_arn(self):
        return self.iam_role_arn()

    def up(self, phase: resource.Phase):
        super().up(phase)
        if not self.iam_role_id:
            with phase.sub(f"creating IAM role {self}") as phase:
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
                    RoleName=self.get_role_name(),
                    AssumeRolePolicyDocument=json.dumps(role_policy)
                )
                self.iam_role_id.select(response['Role']['RoleId'])
                self.iam_role_id.select(response['Role']['Arn'])
                with phase.sub(f'Waiting 5 more seconds for {self} to stabilize in AWS'):
                    time.sleep(10)


    def down(self, phase: resource.Phase):
        if self.iam_role_id:
            with phase.sub(f"deleting IAM role {self}") as phase:
                response = iam_client.delete_role(RoleName=self.get_role_name())

class Method(resource.Resource):
    lambda_name: configurable.Var[str] 
    lambda_arn: configurable.Var[str]
    resource_name: configurable.Var[str]
    method_name: configurable.Var[str]
    rest_api_id: configurable.Var[str]
    api_resource_id: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.lambda_arn = configurable.Var(self, 'lambda_arn')
        self.resource_name = configurable.Var(self, 'resource_name')
        self.method_name = configurable.Var(self, 'method_name')
        self.rest_api_id = configurable.Var(self, 'rest_api_id')
        self.api_resource_id = configurable.Var(self, 'api_resource_id')

    def up(self, phase: resource.Phase):
        with phase.sub(f"Add a method {self.method_name()} to resource {self.resource_name()}") as phase:
            method = api_client.put_method(
                restApiId=self.rest_api_id(),
                resourceId=self.api_resource_id(),
                httpMethod='POST',
                authorizationType='NONE'
            )

            method_res = api_client.put_method_response(
                restApiId=self.rest_api_id(),
                resourceId=self.api_resource_id(),
                httpMethod='POST',
                statusCode='200'
            )

            lambda_version = lambda_client.meta.service_model.api_version

            uri_data = {
                "aws-region": 'us-east-1',
                "api-version": lambda_version,
                "lambda-arn": self.lambda_arn()
            }

            uri = "arn:aws:apigateway:{aws-region}:lambda:path/{api-version}/functions/{lambda-arn}/invocations".format(**uri_data)

            integration = api_client.put_integration(
                restApiId=self.rest_api_id(),
                resourceId=self.api_resource_id(),
                httpMethod='POST',
                type='AWS',
                integrationHttpMethod='POST',
                uri=uri,
                passthroughBehavior='WHEN_NO_MATCH'
            )

            integration_response = api_client.put_integration_response(
                restApiId=self.rest_api_id(),
                resourceId=self.api_resource_id(),
                httpMethod='POST',
                statusCode='200',
                selectionPattern=''
            )

class Resource(resource.Resource):
    lambda_name: configurable.Var[str] 
    lambda_arn: configurable.Var[str]
    resource_name: configurable.Var[str]
    rest_api_id: configurable.Var[str]
    root_resource_id: configurable.Var[str]
    api_resource_id: configurable.Var[str]

    post_method: resource.Ref[Method]


    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.lambda_arn = configurable.Var(self, 'lambda_arn')
        self.resource_name = configurable.Var(self, 'resource_name')
        self.rest_api_id = configurable.Var(self, 'rest_api_id')
        self.root_resource_id = configurable.Var(self, 'root_resource_id')
        self.api_resource_id = configurable.Var(self, 'api_resource_id')

        self.post_method = resource.Ref()

    def elaborate(self, phase: resource.Phase):
        self.post_method.resolve(phase, Method)
        self.post_method().alias(
            lambda_name = self.lambda_name,
            lambda_arn = self.lambda_arn,
            resource_name = self.resource_name,
            method_name = 'POST',
            rest_api_id = self.rest_api_id,
            api_resource_id = self.api_resource_id
        )
        super().elaborate(phase)

    def up(self, phase: resource.Phase):
        if not self.api_resource_id:
            with phase.sub(f"Creating API Gateway Resource {self}") as phase:
                # Create an api resource
                api_resource = api_client.create_resource(
                    restApiId=self.rest_api_id(),
                    parentId=self.root_resource_id(),
                    pathPart=self.resource_name()
                )

                self.api_resource_id.select(api_resource['id'])
        super().up(phase)

    def down(self, phase: resource.Phase):
        if self.api_resource_id:
            with phase.sub(f"Destroying API Gateway Resource {self}") as phase:
                api_client.delete_resource(
                    restApiId=self.rest_api_id(),
                    resourceId=self.api_resource_id()
                )

class API(resource.Resource):
    lambda_name: configurable.Var[str]
    rest_api_id: configurable.Var[str]
    root_resource_id: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.rest_api_id = configurable.Var(self, 'rest_api_id')
        self.root_resource_id = configurable.Var(self, 'root_resource_id')

    def up(self, phase: resource.Phase):
        # Create rest api
        if not self.rest_api_id:
            with phase.sub(f"Creating API Gateway Rest API for {self}") as phase:
                rest_api = api_client.create_rest_api(
                    name=self.lambda_name()
                )

                self.rest_api_id.select(rest_api["id"])

                # Get the rest api's root resource id
                self.root_resource_id.select(api_client.get_resources(
                    restApiId=self.rest_api_id()
                )['items'][0]['id'])

    def down(self, phase: resource.Phase):
        if self.rest_api_id:
            with phase.sub(f"Destroying API Gateway Rest API for {self}") as phase:
                api_client.delete_rest_api(restApiId=self.rest_api_id())

    def deploy(self, phase: resource.Phase):
        # this bit sets a stage 'dev' that is built off the created apigateway
        # it will look something like this:
        # https://<generated_api_id>.execute-api.<region>.amazonaws.com/dev
        with phase.sub(f"Deploying API Gateway {self}") as phase:
            deployment = api_client.create_deployment(
                restApiId=self.rest_api_id(),
                stageName='dev',
            )

        # all that done we can then send a request to invoke our lambda function
        # https://123456.execute-api.us-east-1.amazonaws.com/dev?greeter=John
        print(deployment)

class Function(resource.Resource):
    lambda_name: configurable.Var[str]
    runtime: configurable.Var[str]
    code_dir_local_path: configurable.Var[str]

    execution_role: resource.Ref[ExecutionRole]
    code_dir: resource.Ref[file.LocalFile]

    lambda_arn: configurable.Var[str]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.runtime = configurable.Var(self, 'runtime', 'nodejs14.x')
        self.code_dir_local_path = configurable.Var(self, 'code_dir_local_path')

        self.execution_role = resource.Ref(self, 'execution_role')
        self.code_dir = resource.Ref(self, 'code_dir')

        self.lambda_arn = configurable.Var(self, 'lambda_arn')

    def elaborate(self, phase: resource.Phase):
        self.execution_role.resolve(phase, ExecutionRole)
        self.code_dir.resolve(phase, file.LocalFile)

        self.execution_role().alias(lambda_name=self.lambda_name)
        self.code_dir().alias(local_path=self.code_dir_local_path)

        super().elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        if not self.lambda_arn:
            role = iam_client.get_role(RoleName=self.execution_role().get_role_name())
            with tempfile.NamedTemporaryFile('wb+', delete=False) as zip_file:
                zip_file_path = zip_file.name
                zip_file.close()

            with phase.sub(f"Zipping compiled code image in {self.code_dir().local_path()}") as phase:
                shutil.make_archive(zip_file_path, 'zip', self.code_dir().local_path())
                zip_file_path += '.zip'

            with phase.sub(f"Reading compiled code zip file from {zip_file_path}.zip") as phase:
                with open(zip_file_path, 'rb') as fp:
                    zip_bytes = fp.read()
                    with phase.sub(f"Uploading compiled code zip image of {len(zip_bytes)}B as lambda code") as phase:
                        response = lambda_client.create_function(
                            FunctionName=self.lambda_name(),
                            Runtime=self.runtime(),
                            Handler='index.handler',
                            Role=role['Role']['Arn'],
                            Code=dict(ZipFile=zip_bytes),
                            Timeout=300, # Maximum allowable timeout
                        )
                        self.lambda_arn.select(response['FunctionArn'])

            print(f"DEBUG: lambda_client.create_function response is {response}")

    def down(self, phase: resource.Phase):
        if self.lambda_arn:
            lambda_client.delete_function(
                FunctionName=self.lambda_name()
            )
        super().down(phase)

class Service(resource.Resource):
    function: resource.Ref[Function]
    api: resource.Ref[API]
    _resource: resource.Ref[Resource]

    def __init__(self, resource_path: typing.Union[ None, typing.List[str] ] = None):
        super().__init__(resource_path)
        self.lambda_name = configurable.Var(self, 'lambda_name')
        self.runtime = configurable.Var(self, 'runtime', 'nodejs14.x')
        self.code_dir_local_path = configurable.Var(self, 'code_dir_local_path')

        self.function = resource.Ref(self, 'function')
        self.api = resource.Ref(self, 'api')
        self._resource = resource.Ref(self, '_resource')

    def elaborate(self, phase: resource.Phase):
        self.function.resolve(phase, Function)
        self._resource.resolve(phase, Resource)
        self.api.resolve(phase, API)

        self.function().alias(
            lambda_name=self.lambda_name,
            runtime=self.runtime,
            code_dir_local_path=self.code_dir_local_path
        )
        self.api().alias(
            lambda_name=self.lambda_name
        )
        self._resource().alias(
            lambda_name=self.function().lambda_name,
            lambda_arn=self.function().lambda_arn,
            resource_name=self.lambda_name(),
            rest_api_id=self.api().rest_api_id,
            root_resource_id=self.api().root_resource_id
        )

        super().elaborate(phase)

    def up(self, phase: resource.Phase):
        super().up(phase)
        with phase.sub(f"Give API POST method permission to invoke lambda") as phase:
            uri_data = {
                "aws-region": 'us-east-1',
                "aws-acct-id": self.function().lambda_arn().split(':')[4],
                "aws-api-id": self.api().rest_api_id(),
                "method": "POST",
                "lambda-function-name": self.lambda_name()
            }

            source_arn = "arn:aws:execute-api:{aws-region}:{aws-acct-id}:{aws-api-id}/*/{method}/{lambda-function-name}".format(**uri_data)

            lambda_client.add_permission(
                FunctionName=self.lambda_name(),
                Action="lambda:InvokeFunction",
                Principal="apigateway.amazonaws.com",
                StatementId=uuid.uuid4().hex,
                SourceArn=source_arn
            )

    def deploy(self, phase: resource.Phase):
        self.api().deploy(phase)


parser = argparse.ArgumentParser(description='Spinup cloud cluster')
parser.add_argument('verb', type=str, choices=['create', 'CREATE', 'configure', 'CONFIGURE', 'up', 'UP', 'down', 'DOWN', 'deploy', 'DEPLOY'],
                    help='command verbs: bring cluster UP, take cluster DOWN, WATCH server logs, show service IP address, open SSH shell on service instance')
parser.add_argument('-c', '--config', type=str, help='path to configuration file', required=True)
args, unknown = parser.parse_known_args()

if args.verb in ('create', 'CREATE'):
    parser.add_argument('resource_name', type=str, help='name of the new resource instance')
    args, unknown = parser.parse_known_args()
    if args.resource_name is None:
        raise RuntimeError(f"Must provide a resource_name when creating a resource")
    config = Service([ args.resource_name ])
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
elif args.verb in ('deploy', 'DEPLOY'):
    with resource.Phase(f'cluster_control DEPLOY {config}', persistor, config) as phase:
        config.deploy(phase)
else:
    persistor.save()
