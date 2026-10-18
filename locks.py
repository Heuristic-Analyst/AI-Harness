# locks.py — "in use" signs that every running main.py (an "instance") respects. with them, one conversation or one
# notebook is worked on by one instance at a time, and two instances never save the memory or a skill over each other.
# how: a lock is a file in Locks/. holding it = keeping that file open, with a lock from the operating system on it.
# the operating system takes that lock away by itself when the file is closed or the program ends, however it ends:
# /exit, a crash, a closed terminal, a killed process, even a power cut. so a forgotten lock can't exist.
# what counts is only that OS lock, never whether a file is there. still, no files pile up:
#   - an instance deletes its own lock files when it gives a lock back, and at exit all of them
#   - a crash skips that, so at every start the files nobody holds are deleted: the leftovers of crashed instances.
#     a file another running instance holds is never touched: it has the OS lock on it, so it can't be taken for deleting
# every instance also holds its own lock, "instance-<its id>", as long as it runs: that is how the others see it lives.

import os
import time
import threading
from config import *

if os.name == "nt":                                               # windows locks files one way, mac and linux another
    import msvcrt
else:
    import fcntl

held = {}                                                         # lock name -> its open file: the locks this instance holds
guard = threading.Lock()                                          # parallel tool calls: one changes `held` at a time


def file_of(name):
    return os.path.join(LOCKS_DIR, name + ".lock")

def lock_file(f):
    """try to put the operating system's lock on this open file. True = got it, False = another program has it"""
    try:
        f.seek(0)
        if os.name == "nt":
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)        # NB = don't wait, answer right away
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False

def unlock_file(f):
    try:
        f.seek(0)
        if os.name == "nt":
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    f.close()

def same_file(f, path):
    """is the open file f still the file at path? not if another instance deleted it while we were opening it"""
    try:
        now = os.stat(path)
    except OSError:
        return False
    mine = os.fstat(f.fileno())
    return now.st_ino == mine.st_ino and now.st_dev == mine.st_dev

def take(name):
    """take the lock. True = this instance holds it now (or held it already). False = another instance holds it"""
    with guard:
        if name in held:
            return True
        os.makedirs(LOCKS_DIR, exist_ok=True)
        while True:
            f = open(file_of(name), "a+")                         # "a+" = open it, and create it if it isn't there yet
            if not lock_file(f):
                f.close()
                return False
            if same_file(f, file_of(name)):                       # the normal case
                held[name] = f
                return True
            unlock_file(f)                                        # the holder deleted it while we opened it: we locked a
                                                                  # file that is gone. so once more, with the file there now

def wait_take(name, seconds=5):
    """take the lock, waiting a few seconds if another instance has it. for locks that are only held for a moment"""
    give_up = time.time() + seconds
    while True:
        if take(name):
            return True
        if time.time() >= give_up:
            return False
        time.sleep(0.1)

def drop(f, name):
    """let go of a lock we hold and delete its file"""
    try:
        os.remove(file_of(name))                                  # first delete, then unlock: so nobody can take it in between
    except OSError:                                               # and lose it again. (windows can't delete an open file:
        pass                                                      # there it is tried once more below)
    unlock_file(f)
    if os.name == "nt" and os.path.exists(file_of(name)):
        try:
            os.remove(file_of(name))                              # fails if another instance has it open right now: then it stays
        except OSError:
            pass

def release(name):
    """give the lock back and delete its file. a lock this instance doesn't hold is left alone, and so is its file"""
    with guard:
        f = held.pop(name, None)
        if f:
            drop(f, name)

def release_all(start):
    """give back every lock whose name starts like this, e.g. "notebook-" when the sandbox stops"""
    for name in list(held):                                       # list(...) = a copy, because release changes `held`
        if name.startswith(start):
            release(name)

def free(name):
    """is nobody holding this lock right now? the lock is not kept. a file nobody holds is a leftover, and is deleted"""
    if name in held:
        return False
    try:
        f = open(file_of(name), "r")                              # "r": only look, never create a file
    except FileNotFoundError:
        return True
    if not lock_file(f):                                          # someone holds it: their file, it is left alone
        f.close()
        return False
    if same_file(f, file_of(name)):                               # we got it, so nobody else had it: a leftover of a crash
        drop(f, name)
    else:
        unlock_file(f)                                            # its holder deleted it while we looked: nothing to do
    return True


# --- instances: each holds "instance-<id>" as long as it runs ---
def alive(owner):
    """is the instance with this id still running? it is, as long as its instance lock is held"""
    if owner == INSTANCE:
        return True
    return not free("instance-" + owner)

def start():
    """at startup: take this instance's own lock, then clean up the leftovers of crashed instances: every file in Locks/
    that nobody holds goes. the files of running instances stay, they hold them"""
    take("instance-" + INSTANCE)
    for file in sorted(os.listdir(LOCKS_DIR)):
        if file.endswith(".lock"):
            free(file[:-len(".lock")])                            # deletes the file only if nobody holds it

def stop():
    """at exit: give every lock of this instance back, which deletes its files. (a crash skips this: then the operating
    system releases the locks, and the next start deletes the files)"""
    for name in list(held):                                       # list(...) = a copy, because release changes `held`
        release(name)
