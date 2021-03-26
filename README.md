# Self-Contained Cluster Control Script

For those of us that don't trust Ansible (as we probably should), here is
a completely self-contained cluster control utility that can be used to
spinup a competely working EC2 Virtual Private Cluster to run an Express/NodeJS 10.x
service.

## CREATE

Create an entirely new Cluster configuration from a template.

```
src/control.py create $TEMPLATE_FILE_NAME
```

## UP

Allocate and activate all cloud resources required to run the cluster.

```
src/control.py up
```

## START

```
src/control.py start
```

Start the Express/NodeJS service on all EC2 instances.

## STOP

```
src/control.py stop
```

Stop the Express/NodeJS service on all EC2 instances.

## PULL and BUILD

Update the Express/NodeJS source code on the EC2 instances by
doing git pull.

```
src/control.py pull
src/control.py build
```

## DOWN

De-activate and release all cloud resources that were required to run the cluster.

```
src/control.py down
```

Stop the Express/NodeJS service on all EC2 instances.

If spinning up a cluster fails for any reason, you MUST
spin it down to release AWS resources some of which (e.g.
instances) have nontrivial cost by the minute, and others
of which (e.g. keys) have a capped quota that an be allocated
at any one time.
