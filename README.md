About
=====

Index defined mount points and mount them read-only from cache where the resource is not available (disk unplugged, network not reachable, …).

Configuration
=============

Configuration should be set in a *config.yaml* file.

Example
-------

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

Types
-----

- `disk`: any internal or pluged in disk
- `sshfs`: an ssh connection using sftp
- `local`: a local directory

Pathes
------

- for `disk`, a `udev` unique device path using `UUID`, i.e. starting with `/dev/disk/by-uuid/`.
  `UUID` could be found by running `blkid` command.
- for `sshfs`, a sshfs parameter url: `[login@]host[,port]:path`.
  `port` syntax is an addition to sshfs original url.
- for `local`, a simple real directory path.

Usage
=====

`./pycatalog directory`

The *directory* should contains the *config.yaml* file.

A **mount** directory will appear inside this where you could find your files.
