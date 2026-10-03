"""
pairwise-os-kernel-system - OSKernelSystem

A minimal model of an operating-system kernel providing:

* process scheduling with priorities, time slices and context switches
* paged virtual memory with per-page permissions
* an inode based file system with directories and permissions
* prioritized, nestable interrupts with handler functions
* system calls with argument validation, permission checks and return values
"""

from __future__ import annotations

import math
from collections import deque


class OSKernelSystem:
    KERNEL_FRAMES = 16  # low frames reserved for kernel allocations

    def __init__(self):
        self.state = {}

        # ---- process management ----
        self.time_slice = 10
        self.processes = {}
        self.ready_queue = deque()
        self.current_pid = None
        self._next_pid = 1

        # ---- memory management ----
        self.page_size = 4096
        self.num_frames = 64
        self.frames = {frame: None for frame in range(self.num_frames)}
        self.page_tables = {}
        self._next_vaddr = {}
        self._frame_lru = []
        self.swap = {}

        # ---- file system ----
        self.inodes = {}
        self._next_inode = 1
        self.root_inode = self._create_inode("dir", owner="root",
                                             permissions="rwxr-xr-x")

        # ---- interrupts ----
        self.interrupt_handlers = {}
        self.active_interrupts = []
        self.interrupt_log = []

        # ---- system calls ----
        self._syscalls = {}
        self._register_default_syscalls()

    # ------------------------------------------------------------------
    # Process scheduling: priorities + time slices + context switches
    # ------------------------------------------------------------------
    def create_process(self, name=None, priority=0, time_slice=None,
                       context=None, burst_time=30):
        pid = self._next_pid
        self._next_pid += 1
        pcb = {
            "pid": pid,
            "name": name or "process-%d" % pid,
            "priority": priority,
            "time_slice": time_slice or self.time_slice,
            "context": dict(context or {}),
            "remaining": burst_time,
            "state": "ready",
        }
        self.processes[pid] = pcb
        self.ready_queue.append(pid)
        return pcb

    def schedule_process(self, process=None, **kwargs):
        """Schedule the highest-priority ready process for one time slice.

        Optionally registers a new process first (dict or keyword args).
        Performs a context switch (save outgoing / restore incoming
        context) whenever the running process changes.
        """
        if process is not None or kwargs:
            spec = dict(process) if isinstance(process, dict) else {}
            spec.update(kwargs)
            allowed = {"name", "priority", "time_slice", "context",
                       "burst_time"}
            self.create_process(**{k: v for k, v in spec.items()
                                   if k in allowed})

        if not self.ready_queue:
            return {"scheduled": None, "reason": "no ready processes",
                    "ready_queue": []}

        candidates = list(self.ready_queue)
        best_pid = max(
            candidates,
            key=lambda p: (self.processes[p]["priority"],
                           -candidates.index(p)),
        )
        self.ready_queue.remove(best_pid)
        pcb = self.processes[best_pid]

        context_switch = (self.current_pid is not None
                          and self.current_pid != best_pid)
        saved_context = restored_context = None
        if context_switch:
            outgoing = self.processes[self.current_pid]
            if outgoing["state"] == "running":
                outgoing["state"] = "ready"
            saved_context = dict(outgoing["context"])
            restored_context = dict(pcb["context"])

        self.current_pid = best_pid
        pcb["state"] = "running"

        quantum = pcb["time_slice"]
        pcb["remaining"] -= quantum
        if pcb["remaining"] <= 0:
            pcb["state"] = "terminated"
        else:
            self.ready_queue.append(best_pid)

        return {
            "scheduled": best_pid,
            "pid": best_pid,
            "priority": pcb["priority"],
            "time_slice": quantum,
            "remaining": pcb["remaining"],
            "state": pcb["state"],
            "context_switch": context_switch,
            "saved_context": saved_context,
            "restored_context": restored_context,
            "ready_queue": list(self.ready_queue),
        }

    # ------------------------------------------------------------------
    # Memory management: paging + virtual memory + permissions
    # ------------------------------------------------------------------
    def allocate_memory(self, size=None, *, pid=None, permissions="rw",
                        user="user", **kwargs):
        """Allocate ``size`` bytes of paged virtual memory.

        Pages are mapped to physical frames on demand; when physical
        memory is exhausted the least-recently-used frame is swapped out
        (virtual memory).  Each page carries r/w/x permissions and
        user-mode allocations can never receive kernel-reserved frames.
        """
        if size is None:
            return {
                "page_size": self.page_size,
                "total_frames": self.num_frames,
                "free_frames": sum(1 for o in self.frames.values()
                                   if o is None),
                "swap_pages": len(self.swap),
            }
        if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
            raise ValueError("size must be a positive integer")
        if not permissions or not set(permissions) <= set("rwx"):
            raise ValueError("permissions must be a non-empty subset of 'rwx'")

        pid = 0 if pid is None else pid
        kernel = user == "kernel"
        pages_needed = math.ceil(size / self.page_size)
        table = self.page_tables.setdefault(pid, {})
        base = self._next_vaddr.get(pid, 0)

        frames_used = []
        swapped = 0
        for i in range(pages_needed):
            page_no = base // self.page_size + i
            frame, did_swap = self._claim_frame(pid, page_no, kernel)
            table[page_no] = {"frame": frame, "permissions": permissions,
                              "kernel": kernel}
            frames_used.append(frame)
            swapped += int(did_swap)
        self._next_vaddr[pid] = base + pages_needed * self.page_size

        return {
            "pid": pid,
            "address": base,
            "size": size,
            "pages": pages_needed,
            "frames": frames_used,
            "permissions": permissions,
            "swapped_out": swapped,
            "kernel": kernel,
        }

    def _map_frame(self, frame, pid, page_no):
        self.frames[frame] = (pid, page_no)
        if frame in self._frame_lru:
            self._frame_lru.remove(frame)
        self._frame_lru.append(frame)

    def _claim_frame(self, pid, page_no, kernel):
        for frame in range(self.num_frames):
            if self.frames[frame] is None and (kernel
                                               or frame >= self.KERNEL_FRAMES):
                self._map_frame(frame, pid, page_no)
                return frame, False
        # virtual memory: evict the least-recently-used frame to swap
        for frame in list(self._frame_lru):
            owner = self.frames[frame]
            if owner is None:
                continue
            if not kernel and frame < self.KERNEL_FRAMES:
                continue
            old_pid, old_page = owner
            self.swap[(old_pid, old_page)] = \
                self.page_tables[old_pid].pop(old_page)
            self._frame_lru.remove(frame)
            self._map_frame(frame, pid, page_no)
            return frame, True
        raise MemoryError("out of memory")

    def check_memory_access(self, pid, address, mode="r", user="user"):
        """Return True only if the access is permitted by the page table."""
        page_no = address // self.page_size
        entry = self.page_tables.get(pid, {}).get(page_no)
        if entry is None:
            return False
        if entry["kernel"] and user != "kernel":
            return False
        return mode in entry["permissions"]

    # ------------------------------------------------------------------
    # File system: inodes + directories + permissions
    # ------------------------------------------------------------------
    def _create_inode(self, kind, owner, permissions, data=None):
        ino = self._next_inode
        self._next_inode += 1
        self.inodes[ino] = {
            "inode": ino,
            "type": kind,
            "owner": owner,
            "permissions": permissions,
            "data": data,
            "children": {} if kind == "dir" else None,
        }
        return ino

    def _lookup(self, path):
        if not isinstance(path, str) or not path.startswith("/"):
            raise ValueError("path must be an absolute path")
        node = self.root_inode
        for part in [p for p in path.split("/") if p]:
            inode = self.inodes[node]
            if inode["type"] != "dir" or part not in inode["children"]:
                return None
            node = inode["children"][part]
        return node

    def _perm_allowed(self, inode, mode, user):
        if user == "root":
            return True
        perms = inode["permissions"]
        triplet = perms[0:3] if user == inode["owner"] else perms[6:9]
        return mode in triplet

    def mkdir(self, path, *, user="root", permissions="rwxr-xr-x"):
        parent_path, _, name = path.rstrip("/").rpartition("/")
        parent = self._lookup(parent_path or "/")
        if parent is None or self.inodes[parent]["type"] != "dir":
            raise FileNotFoundError("parent directory does not exist")
        if not self._perm_allowed(self.inodes[parent], "w", user):
            raise PermissionError("cannot create directory here")
        ino = self._create_inode("dir", owner=user, permissions=permissions)
        self.inodes[parent]["children"][name] = ino
        return {"inode": ino, "path": path, "type": "dir"}

    def read_write_file(self, path=None, data=None, mode=None, *,
                        user="root", permissions="rw-r--r--", **kwargs):
        """Read from or write to a file identified by an absolute path.

        Files live in directories and are backed by inodes that store the
        data plus ownership/permission metadata.  Reads return the file
        contents; writes return a result dict with the inode number.
        """
        if path is None:
            return {"inodes": len(self.inodes), "root": "/",
                    "next_inode": self._next_inode}
        if mode is None:
            mode = "w" if data is not None else "r"
        if "w" in mode:
            return self._write_file(path, "" if data is None else data,
                                    user, permissions)
        return self._read_file(path, user)

    def _write_file(self, path, data, user, permissions):
        ino = self._lookup(path)
        if ino is not None:
            inode = self.inodes[ino]
            if inode["type"] != "file":
                raise IsADirectoryError(path)
            if not self._perm_allowed(inode, "w", user):
                raise PermissionError("write permission denied")
            inode["data"] = data
            return {"inode": ino, "path": path, "bytes": len(data),
                    "created": False}
        parent_path, _, name = path.rpartition("/")
        parent = self._lookup(parent_path or "/")
        if parent is None or self.inodes[parent]["type"] != "dir":
            raise FileNotFoundError("parent directory does not exist")
        if not self._perm_allowed(self.inodes[parent], "w", user):
            raise PermissionError("cannot create file here")
        ino = self._create_inode("file", owner=user,
                                 permissions=permissions, data=data)
        self.inodes[parent]["children"][name] = ino
        return {"inode": ino, "path": path, "bytes": len(data),
                "created": True}

    def _read_file(self, path, user):
        ino = self._lookup(path)
        if ino is None:
            raise FileNotFoundError(path)
        inode = self.inodes[ino]
        if inode["type"] != "file":
            raise IsADirectoryError(path)
        if not self._perm_allowed(inode, "r", user):
            raise PermissionError("read permission denied")
        return inode["data"]

    # ------------------------------------------------------------------
    # Interrupts: priorities + nesting + handler functions
    # ------------------------------------------------------------------
    def register_interrupt(self, irq, handler=None, priority=0):
        if handler is None:
            def handler(event, _irq=irq):
                self.interrupt_log.append(("default-handler", _irq))
                return "handled"
        self.interrupt_handlers[irq] = {"handler": handler,
                                        "priority": priority}
        return {"irq": irq, "priority": priority, "registered": True}

    def handle_interrupt(self, irq=None, *, priority=None, handler=None,
                         **kwargs):
        """Register or raise an interrupt.

        Higher-priority interrupts preempt (nest into) lower-priority
        ones; the preempted interrupt resumes once the handler returns.
        Every interrupt is dispatched to a handler function.
        """
        if irq is None:
            return {
                "registered": sorted(self.interrupt_handlers),
                "active": [i["irq"] for i in self.active_interrupts],
                "log": list(self.interrupt_log),
            }
        if handler is not None:
            return self.register_interrupt(
                irq, handler, 0 if priority is None else priority)
        if irq not in self.interrupt_handlers:
            self.register_interrupt(irq, None,
                                    0 if priority is None else priority)

        entry = self.interrupt_handlers[irq]
        prio = entry["priority"] if priority is None else priority

        preempted = []
        while (self.active_interrupts
               and self.active_interrupts[-1]["priority"] < prio):
            prev = self.active_interrupts.pop()
            preempted.append(prev)
            self.interrupt_log.append(("preempt", prev["irq"]))

        self.active_interrupts.append({"irq": irq, "priority": prio})
        self.interrupt_log.append(("handle", irq))
        result = entry["handler"]({"irq": irq, "priority": prio})
        self.active_interrupts.pop()

        for prev in reversed(preempted):
            self.active_interrupts.append(prev)
            self.interrupt_log.append(("resume", prev["irq"]))

        return {
            "irq": irq,
            "priority": prio,
            "handled": True,
            "result": result,
            "preempted": [p["irq"] for p in preempted],
            "nested": bool(preempted),
        }

    # ------------------------------------------------------------------
    # System calls: argument checks + permission checks + return values
    # ------------------------------------------------------------------
    def register_syscall(self, name, func, *, arg_count=None,
                         arg_types=None, permission="user"):
        self._syscalls[name] = {
            "func": func,
            "arg_count": arg_count,
            "arg_types": tuple(arg_types) if arg_types else None,
            "permission": permission,
        }
        return {"syscall": name, "permission": permission,
                "registered": True}

    def _register_default_syscalls(self):
        self.register_syscall("schedule", lambda: self.schedule_process(),
                              arg_count=0)
        self.register_syscall("alloc", lambda size: self.allocate_memory(size),
                              arg_count=1, arg_types=(int,))
        self.register_syscall("read_file",
                              lambda path: self.read_write_file(path),
                              arg_count=1, arg_types=(str,))
        self.register_syscall(
            "write_file",
            lambda path, data: self.read_write_file(path, data),
            arg_count=2, arg_types=(str, str))
        self.register_syscall("kernel_log",
                              lambda: list(self.interrupt_log),
                              arg_count=0, permission="kernel")

    def syscall(self, name=None, *args, caller="user", **kwargs):
        """Invoke a registered system call.

        Validates the arguments, enforces user/kernel permissions and
        always reports success or failure through the return value.
        """
        if name is None:
            return {"syscalls": sorted(self._syscalls),
                    "count": len(self._syscalls)}
        entry = self._syscalls.get(name)
        if entry is None:
            return {"status": "error",
                    "error": "unknown syscall: %s" % name,
                    "return_value": None}
        if entry["permission"] == "kernel" and caller != "kernel":
            return {"status": "error", "error": "permission denied",
                    "return_value": None}
        if entry["arg_count"] is not None and len(args) != entry["arg_count"]:
            return {"status": "error", "error": "invalid argument count",
                    "return_value": None}
        if entry["arg_types"] is not None and (
                len(args) != len(entry["arg_types"])
                or any(not isinstance(a, t)
                       for a, t in zip(args, entry["arg_types"]))):
            return {"status": "error", "error": "invalid argument types",
                    "return_value": None}
        try:
            result = entry["func"](*args, **kwargs)
        except (ValueError, TypeError, PermissionError, FileNotFoundError,
                MemoryError) as exc:
            return {"status": "error", "error": str(exc),
                    "return_value": None}
        return {"status": "success", "return_value": result}
