#!/usr/bin/env python3
import stat
import unittest

from ..inode import InodeOwner, InodeUtimes
from ..incomplete_inode import (
    IncompleteDevice, IncompleteDir, IncompleteFifo, IncompleteFile,
    IncompleteSocket, IncompleteSymlink,
)
from ..parse_dump import SendStreamItem, SendStreamItems as SSI


class IncompleteInodeTestCase(unittest.TestCase):

    def test_incomplete_file_including_common_attributes(self):
        ino = IncompleteFile(item=SSI.mkfile(path=b'a'))

        self.assertEqual('(File)', repr(ino))

        self.assertEqual({}, ino.xattrs)
        self.assertIs(None, ino.owner)
        self.assertIs(None, ino.mode)
        self.assertIs(None, ino.utimes)
        self.assertEqual(stat.S_IFREG, ino.file_type)

        ino.apply_item(SSI.truncate(path=b'a', size=17))
        self.assertEqual('(File h17)', repr(ino))

        ino.apply_item(SSI.write(path=b'a', offset=10, data=b'x' * 15))
        self.assertEqual('(File h10d15)', repr(ino))

        ino.apply_item(SSI.update_extent(path=b'a', offset=40, len=5))
        self.assertEqual('(File h10d15h15d5)', repr(ino))

        ino.apply_item(SSI.set_xattr(path=b'a', name=b'cat', data=b'nip'))
        self.assertEqual({b'cat': b'nip'}, ino.xattrs)

        ino.apply_item(SSI.remove_xattr(path=b'a', name=b'cat'))
        self.assertEqual({}, ino.xattrs)

        with self.assertRaisesRegex(KeyError, 'cat'):
            ino.apply_item(SSI.remove_xattr(path=b'a', name=b'cat'))

        # Test the `setuid` bit while we are at it.
        ino.apply_item(SSI.chmod(path=b'a', mode=0o4733))
        self.assertEqual(0o4733, ino.mode)

        with self.assertRaisesRegex(RuntimeError, 'cannot change file type'):
            ino.apply_item(SSI.chmod(path=b'a', mode=0o104733))

        ino.apply_item(SSI.chown(path=b'a', uid=10, gid=20))
        self.assertEqual(InodeOwner(uid=10, gid=20), ino.owner)

        t = 10 ** 8  # tenth of a second in nanoseconds
        ino.apply_item(SSI.utimes(
            path=b'a', ctime=(1, 9 * t), mtime=(2, 8 * t), atime=(1, 7 * t),
        ))
        self.assertEqual(
            InodeUtimes(ctime=(1, 9 * t), mtime=(2, 8 * t), atime=(1, 7 * t)),
            ino.utimes,
        )

        self.assertEqual(
            '(File o10:20 m4733 t70/01/01.00:00:01.9+0.9-1.1 h10d15h15d5)',
            repr(ino)
        )

        class FakeItem(metaclass=SendStreamItem):
            pass

        with self.assertRaisesRegex(RuntimeError, 'cannot apply FakeItem'):
            ino.apply_item(FakeItem(path=b'a'))

    # These have no special logic, so this exercise is mildly redundant,
    # but hey, unexecuted Python is a dead, smelly, broken Python.
    def test_simple_file_types(self):
        for item_type, file_type, inode_type, ino_repr in (
            (SSI.mkdir, stat.S_IFDIR, IncompleteDir, '(Dir)'),
            (SSI.mkfifo, stat.S_IFIFO, IncompleteFifo, '(FIFO)'),
            (SSI.mksock, stat.S_IFSOCK, IncompleteSocket, '(Sock)'),
        ):
            ino = inode_type(item=item_type(path=b'a'))
            self.assertEqual(ino_repr, repr(ino))
            self.assertEqual(file_type, ino.file_type)

    def test_devices(self):
        ino_chr = IncompleteDevice(
            item=SSI.mknod(path=b'chr', mode=0o20711, dev=0x123),
        )
        self.assertEqual('(Char m711 123)', repr(ino_chr))
        self.assertEqual(stat.S_IFCHR, ino_chr.file_type)
        self.assertEqual(0x123, ino_chr.dev)
        self.assertEqual(0o711, ino_chr.mode)

        ino_blk = IncompleteDevice(
            item=SSI.mknod(path=b'blk', mode=0o60544, dev=0x345),
        )
        self.assertEqual('(Block m544 345)', repr(ino_blk))
        self.assertEqual(stat.S_IFBLK, ino_blk.file_type)
        self.assertEqual(0x345, ino_blk.dev)
        self.assertEqual(0o544, ino_blk.mode)

        with self.assertRaisesRegex(RuntimeError, 'unexpected device mode'):
            IncompleteDevice(
                item=SSI.mknod(path=b'e', mode=0o10644, dev=3),
            )

    def test_symlink(self):
        ino = IncompleteSymlink(item=SSI.symlink(path=b'l', dest=b'cat'))

        self.assertEqual(stat.S_IFLNK, ino.file_type)
        self.assertEqual(b'cat', ino.dest)

        self.assertEqual(None, ino.owner)
        ino.apply_item(SSI.chown(path=b'l', uid=1, gid=2))
        self.assertEqual(InodeOwner(uid=1, gid=2), ino.owner)

        self.assertEqual(None, ino.mode)
        with self.assertRaisesRegex(RuntimeError, 'cannot chmod symlink'):
            ino.apply_item(SSI.chmod(path=b'l', mode=0o644))

        self.assertEqual('(Symlink o1:2 cat)', repr(ino))


if __name__ == '__main__':
    unittest.main()
