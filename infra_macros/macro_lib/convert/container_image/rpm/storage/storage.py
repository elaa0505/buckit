#!/usr/bin/env python3
'''
RPM files can be quite big, so we do not necessarily want to commit them
directly to a version control system (most do not cope well with
frequently-changing large binary blobs).

The Storage abstraction in this file (see class docblock) provides a way
of storing RPM blobs either on the local filesystem, or on a remote,
distributed large blob storage, in a transparent way.

Then, the only thing we then need to version is an index of "repo file" to
"storage ID", which is quite VCS-friendly when emitted as e.g. sorted JSON.
'''

import json
import logging

from contextlib import AbstractContextManager
from typing import Callable, ContextManager, IO, Mapping

log = logging.getLogger(__name__)


class StorageOutput:
    '''
    Constructed by Storage.writer(). Call .write() to add data to the blob
    being stored.
    '''
    _commit_callback: Callable[[bool], str]
    _output: IO

    def __init__(self, *, output: IO, commit_callback: '_CommitCallback'):
        self._output = output
        self._commit_callback = commit_callback

    def write(self, data: bytes):
        self._output.write(data)

    def commit(self, *, remove_on_exception=False) -> str:
        '''
        Prevents further writes to the blob, and returns its ID.  Frees any
        resources associated with ongoing writes to this blob.

        If you fail to call `commit()` **OR** if the `Storage.writer()`
        context handles an exception and `commit(remove_on_exception=True)`
        was called, then the partially written blob will be removed.

        Combining `remove_on_exception` with `contextlib.ExitStack` allows
        you to write multiple blobs in an all-or-nothing fashion -- if any
        failure occurs, all written blobs are automatically deleted.  While
        not truly transactional, this is still very useful.
        '''
        self._output = None  # Prevent future write attempts.
        # NB: _CommitCallback raises on double-commits.
        return self._commit_callback(remove_on_exception=remove_on_exception)


class StorageInput:
    '''
    Constructed by Storage.reader(). Use .read() to get data from a
    previously stored blob.
    '''
    _input: IO

    def __init__(self, *, input: IO):
        self._input = input

    def read(self, size=None):
        return self._input.read() if size is None else self._input.read(size)


class Storage:
    '''
    Base class for all storage implementations. See FilesystemStorage for
    a simple implementation. Usage:

        # Storage engines should take only plain-old-data keyword arguments,
        # so that they can be configured from outside Python code via
        # `parse_config`.  Parameters other than 'name' are engine-specific.
        storage = Storage.make('filesystem', base_dir=path)

        with storage.writer() as out:
            out.write('various')
            out.write('data')
            sid = out.commit(remove_on_exception=True)
        print(f'Stored as {sid}')

        with storage.reader(sid) as r:
            print(f'Read back: {r.read()}')

        # NB: removed IDs may remain readable for some time if cleanup is lazy
        storage.remove(sid)
    '''

    NAME_TO_CLS: Mapping[str, 'Storage'] = {}

    def __init_subclass__(cls, storage_name: str, **kwargs):
        super().__init_subclass__(**kwargs)
        Storage.NAME_TO_CLS[storage_name] = cls

    @classmethod
    def parse_config(cls, json_cfg):
        'Uniform parsing for Storage configs e.g. on the command-line.'
        cfg = json.loads(json_cfg)
        cfg['name']  # KeyError if not set, or if not a dict
        return cfg

    @classmethod
    def make(cls, name, **kwargs):
        return cls.NAME_TO_CLS[name](**kwargs)


class _CommitCallback(AbstractContextManager):
    '''
    Ensures the same commit semantics for every storage implementation.
    They only need to provide a `get_id_and_release_resources` context
    manager, which supplies the blob ID at commit time.  Its form is:

        @contextmanager
        def get_id_and_release_resources():
            yield compute_id()
            # Delay clean-up until after the ID is known, so that clean-up
            # errors do not prevent us from learning the ID, which may be
            # needed to later remove the already-written blob.
            release_resources_that_were_held_for_the_blob_write()
    '''

    def __init__(
        self, storage: Storage, get_id_and_release_resources: ContextManager,
    ):
        self.storage = storage
        self.get_id_and_release_resources = get_id_and_release_resources
        self.id = None  # Populated via `get_id_and_release_resources()`
        self.remove = True  # Remove the blob if commit is not called
        self.remove_on_exception = False

    def __call__(self, *, remove_on_exception: bool):
        if self.get_id_and_release_resources is None:
            raise AssertionError('Cannot commit twice')

        # These assignments must come first, so that `__exit__` can safely
        # use `commit`, even if `get_id_and_release_resources` raises.
        get_id_and_release_resources = self.get_id_and_release_resources
        self.remove_on_exception = remove_on_exception
        self.get_id_and_release_resources = None  # Detect double-commits

        with get_id_and_release_resources() as id:
            self.id = id
            # If exiting the context raises an error, `self.remove` is still
            # True, which will trigger auto-cleanup of `self.id`.  This is
            # intended: the storage implementation has signaled some error
            # despite having stored the blob, and we will be able to try to
            # remove it, rather than pass on the possibly-bad ID to the
            # caller.
            assert self.remove

        # The blob is committed and we will definitely succeed in returning
        # the ID to the client, so disable automatic cleanup.
        self.remove = False

        return self.id

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        # The end user never called `commit`, so they did not get an ID, and
        # we should try to clean up.
        if self.get_id_and_release_resources is not None:
            assert self.id is None
            assert self.remove
            try:
                # NB: If any of our storage implementation supported an
                # explicit "abort" feature, we could plumb it through here,
                # and tell the implementation to avoid committing altogether.
                self(remove_on_exception=True)
                self.remove = True
            except BaseException:  # pragma: no cover
                # Mask the exception -- it came from our automatic attempt
                # to release resources, so the end user should not care.  By
                # carrying on, we get to try to remove the ID if
                # `get_id_and_release_resources` returned one, and then
                # raised during its clean-up.
                log.exception(
                    f'Error retrieving ID from {self.storage} while trying '
                    'to automatically clean up an uncommitted blob.'
                )

        if exc_type:
            # `self` must have been called, by the user, or just above.
            if self.remove_on_exception:
                assert self.get_id_and_release_resources is None
                self.remove = True

        if self.remove and self.id:
            self.storage.remove(self.id)

        return False  # This context manager does not suppress exceptions