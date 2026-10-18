# locks.py — "in use" signs that every running main.py (an "instance") respects. with them, one conversation or one
# notebook is worked on by one instance at a time, and two instances never save the memory or a skill over each other.
# how: a lock is a file in Locks/. holding it = keeping that file open, with a lock from the operating system on it.
# the operating system takes that lock away by itself when the file is closed or the program ends, however it ends:
# /exit, a crash, a closed terminal, a killed process, even a power cut. so a forgotten lock can't exist.
# what counts is only that OS lock, never whether a file is there. so the files may stay: empty, 0 bytes each.
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

def take(name):
    """take the lock. True = this instance holds it now (or held it already). False = another instance holds it"""
    with guard:
        if name in held:
            return True
        os.makedirs(LOCKS_DIR, exist_ok=True)
        f = open(file_of(name), "a+")                             # "a+" = open it, and create it if it isn't there yet
        if not lock_file(f):
            f.close()
            return False
        held[name] = f
        return True

def wait_take(name, seconds=5):
    """take the lock, waiting a few seconds if another instance has it. for locks that are only held for a moment"""
    give_up = time.time() + seconds
    while True:
        if take(name):
            return True
        if time.time() >= give_up:
            return False
        time.sleep(0.1)

def release(name):
    """give the lock back. a lock this instance doesn't hold is left alone"""
    with guard:
        f = held.pop(name, None)
    if f:
        unlock_file(f)

def release_all(start):
    """give back every lock whose name starts like this, e.g. "notebook-" when the sandbox stops"""
    for name in list(held):                                       # list(...) = a copy, because release changes `held`
        if name.startswith(start):
            release(name)

def free(name):
    """is nobody holding this lock right now? only looks: the lock is not kept"""
    if name in held:
        return False
    if not os.path.exists(file_of(name)):
        return True
    f = open(file_of(name), "a+")
    if lock_file(f):                                              # we got it, so nobody else has it
        unlock_file(f)
        return True
    f.close()
    return False


# --- instances: each holds "instance-<id>" as long as it runs ---
def alive(owner):
    """is the instance with this id still running? it is, as long as its instance lock is held"""
    if owner == INSTANCE:
        return True
    if free("instance-" + owner):
        try:
            os.remove(file_of("instance-" + owner))               # it is gone: its file isn't needed anymore. ids are never reused
        except OSError:
            pass
        return False
    return True

def start():
    """at startup: take this instance's own lock, and remove the files of instances that ended"""
    take("instance-" + INSTANCE)
    for file in sorted(os.listdir(LOCKS_DIR)):
        if file.startswith("instance-") and file.endswith(".lock"):
            alive(file[len("instance-"):-len(".lock")])           # removes the file if that instance is gone

def stop():
    """at exit: give every lock back and remove this instance's own file. (a crash skips this: then the operating
    system releases the locks, and the next instance that starts removes the file)"""
    for name in list(held):
        release(name)
    try:
        os.remove(file_of("instance-" + INSTANCE))
    except OSError:
        pass
