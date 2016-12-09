About
=====

Index defined mount points and mount them read-only from cache where the resource is not available (disk unplugged, network not reachable, …).

Configuration
=============

*config.yaml* file:

```yaml
remotes:
	- name: my-remote-host
		type: sshfs
		path: user@host:path
	- name: my-passport
		type: disk
		path: /dev/disk/by-uuid/3df07bb7-0182-4744-92f7-3e96dc16dbe7
	- name: on-pc
		type: local
		path: /local-path
```

Usage
=====

`./pycatalog directory`

The *directory* should contains the *config.yaml* file.

A **mount** directory will appear inside this where you could find your files.
