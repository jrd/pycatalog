#!/usr/bin/env python3
# coding: utf-8
# vim: et ts=4 sts=4 st=4 sw=4

import os
import sys
import llfuse
from argparse import ArgumentParser
import errno
from logging import getLogger, Formatter, StreamHandler, INFO, DEBUG
import stat
from time import time
from llfuse import FUSEError
from os import fsencode, fsdecode
from os.path import dirname, basename
import dbus
import faulthandler


faulthandler.enable()
log = getLogger(__name__)


class PhantomFile:
    _dir_type = 'd'
    _sym_type = 'l'

    def __init__(self, filename, filetype, filesize):
        self.filename = filename
        self.filetype = filetype
        self.filesize = int(filesize)

    def is_dir(self):
        return self.filetype == self._dir_type

    def is_symlink(self):
        return self.filetype == self._sym_type

    def __str__(self):
        return '%s%s (%db)' % (self.filename, '/' if self.is_dir() else '', self.filesize)

    def __repr__(self):
        return str(self)


class Operations(llfuse.Operations):

    _directory_mode = (stat.S_IFDIR | stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    _file_mode = (stat.S_IFREG | stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
    _symlink_mode = (stat.S_IFLNK | stat.S_IRUSR | stat.S_IXUSR | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH)
    _notif_item = 'org.freedesktop.Notifications'
    _notif_path = '/' + _notif_item.replace('.', '/')
    _notif_interface = _notif_item
    _notif_app_name = 'PhantomFS'
    _notif_id = hash(_notif_app_name) % 2**32
    _notif_icon = 'face-sad'
    _notif_time_sec = 10
    _notif_max_wait_sec = 1
    
    def __init__(self, lsfile, mountpoint):
        super().__init__()
        self._name = os.path.splitext(basename(lsfile))[0]
        self._mountpoint = mountpoint
        self._notify_object = self._get_notify_object()
        self._last_notification = time()
        self._pfiles = dict([(pf.filename, pf) for pf in [PhantomFile(*line.strip().split(':')) for line in open(lsfile, 'r').readlines()]])
        log.debug([self._pfiles[filename] for filename in self._pfiles if '/' not in filename])
        self._last_inode = None
        self._inodes_mapping = dict()
        self._pathes_mapping = dict()
        self._stamp = int(time() * 1e9)
        self._tried_open_files = []
        self._create_inode()

    def _get_notify_object(self):
        bus = dbus.SessionBus()
        notif = bus.get_object(self._notif_item, self._notif_path)
        return dbus.Interface(notif, self._notif_interface)

    def _notify(self, name):
        if name in self._tried_open_files and time() - self._last_notification > self._notif_max_wait_sec:
            title = 'Cannot access %s' % name
            fullname = os.path.join(self._mountpoint, name)
            text = 'In order to access\n<i>%s</i>,\nyou must mount <b>%s</b>.' % (fullname, self._name)
            self._notify_object.Notify(self._notif_app_name, self._notif_id, self._notif_icon, title, text, '', {}, self._notif_time_sec * 1000)
            self._last_notification = time()
            raise llfuse.FUSEError(errno.EPERM)

    def _create_inode(self, path=None):
        if path is None:
            inode = llfuse.ROOT_INODE
            path = ''
        else:
            inode = self._last_inode + 1
        self._inodes_mapping[inode] = path
        self._pathes_mapping[path] = inode
        self._last_inode = inode
        return inode
    
    def _get_phantom_file_from_path(self, path):
        try:
            return self._pfiles[path]
        except KeyError:
            return None

    def _get_phantom_file_from_inode(self, inode):
        try:
            return self._get_phantom_file_from_path(self._inodes_mapping[inode])
        except KeyError:
            return None

    def _get_inode_from_path(self, path):
        try:
            inode = self._pathes_mapping[path]
        except KeyError as e:
            if path in self._pfiles.keys():
                inode = self._create_inode(path)
            else:
                raise e
        return inode

    def getattr(self, inode, ctx=None):
        entry = llfuse.EntryAttributes()
        pfile = self._get_phantom_file_from_inode(inode)
        log.debug("getattr for %d is %s" % (inode, pfile))
        if pfile is None:
            raise llfuse.FUSEError(errno.ENOENT)
        elif pfile.is_dir():
            entry.st_mode = self._directory_mode
        elif pfile.is_symlink():
            entry.st_mode = self._symlink_mode
        else:
            entry.st_mode = self._file_mode
        entry.st_size = pfile.filesize
        entry.st_atime_ns = self._stamp
        entry.st_ctime_ns = self._stamp
        entry.st_mtime_ns = self._stamp
        entry.st_gid = os.getgid()
        entry.st_uid = os.getuid()
        entry.st_ino = inode
        return entry

    def lookup(self, parent_inode, name, ctx=None):
        name = fsdecode(name)
        log.debug("lookup in %d for %s" % (parent_inode, name))
        if name == '.':
            inode = parent_inode
        if name == '..':
            if parent_inode == llfuse.ROOT_INODE:
                inode = parent_inode
            else:
                try:
                    parent_name = dirname(self._inodes_mapping[parent_inode])
                    inode = self._pathes_mapping[parent_name]
                except KeyError:
                    raise llfuse.FUSEError(errno.ENOENT)
        else:
            try:
                parent_name = self._inodes_mapping[parent_inode]
                inode = self._get_inode_from_path(os.path.join(parent_name, name))
            except KeyError:
                raise llfuse.FUSEError(errno.ENOENT)
        return self.getattr(inode)

    def opendir(self, inode, ctx=None):
        return inode

    def readdir(self, inode, from_inode):
        name = self._inodes_mapping[inode]
        log.debug("readdir for %s" % name)
        if name == '':
            prefix = name
            find_offset = len(prefix) + 1
        else:
            prefix = os.path.join(name, '')
            find_offset = len(prefix)
        # direct children only
        contents = [f for f in self._pfiles.keys() if f != prefix and f.startswith(prefix) and f.find('/', find_offset) == -1]
        log.debug(contents)
        for f in sorted(contents):
            f_inode = self._get_inode_from_path(f)
            if f_inode > from_inode:
                yield (fsencode(basename(f)), self.getattr(f_inode), f_inode)

    def fsyncdir(self, inode, datasync):
        pass

    def releasedir(self, inode):
        pass

    def open(self, inode, flags, ctx=None):
        if inode in self._inodes_mapping:
            name = self._inodes_mapping[inode]
            self._notify(name)
            # this will not happen if the notify is successful
            self._tried_open_files.append(name)
            return inode
        else:
            raise llfuse.FUSEError(errno.ENOENT)

    def read(self, inode, offset, size):
        """Implementing this method is required because some filemanager tries to open and read files to determine their types"""
        log.debug("read %d bytes from %d for inode %d" % (size, offset, inode))
        return b'This file is not accessible\n' if offset == 0 else b''

    def write(self, inode, offset, buffer):
        raise llfuse.FUSEError(errno.EPERM)
        
    def flush(self, inode):
        pass

    def fsync(self, inode, datasync):
        pass

    def release(self, inode):
        pass

    def statfs(self, ctx=None):
        return llfuse.StatvfsData()


def init_logging(debug=False):
    handler = StreamHandler()
    handler.setFormatter(Formatter('%(asctime)s.%(msecs)03d %(threadName)s: [%(name)s] %(message)s', datefmt="%Y-%m-%d %H:%M:%S"))
    root_logger = getLogger()
    if debug:
        handler.setLevel(DEBUG)
        root_logger.setLevel(DEBUG)
    else:
        handler.setLevel(INFO)
        root_logger.setLevel(INFO)
    root_logger.addHandler(handler)


def parse_args(args):
    '''Parse command line'''
    parser = ArgumentParser()
    parser.add_argument('lsfile', type=str,
                        help='.ls file from which to create a phantom')
    parser.add_argument('mountpoint', type=str,
                        help='Where to mount the file system')
    parser.add_argument('--single', action='store_true', default=False,
                        help='Run single threaded')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Enable debugging output')
    parser.add_argument('--debug-fuse', action='store_true', default=False,
                        help='Enable FUSE debugging output')
    return parser.parse_args(args)


def main(args):
    options = parse_args(args)
    init_logging(options.debug)
    operations = Operations(options.lsfile, options.mountpoint)
    log.debug('Mounting...')
    fuse_options = set(llfuse.default_options)
    fuse_options.add('fsname=phantomfs')
    if options.debug_fuse:
        fuse_options.add('debug')
    llfuse.init(operations, options.mountpoint, fuse_options)
    try:
        log.debug('Entering main loop..')
        if options.single:
            llfuse.main(workers=1)
        else:
            llfuse.main()
    except:
        llfuse.close()
        raise
    log.debug('Unmounting..')
    llfuse.close()

if __name__ == '__main__':
    main(sys.argv[1:])
