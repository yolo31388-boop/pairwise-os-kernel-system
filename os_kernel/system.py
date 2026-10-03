"""
pairwise-os-kernel-system - OSKernelSystem

This module contains a deliberately broken implementation.
Fix all bugs so that tests pass.
"""


class OSKernelSystem:
    def __init__(self):
        self.state = {}

    def schedule_process(self, *args, **kwargs):
        """BUG: 进程调度不做优先级，所有进程一样"""
        return None

    def allocate_memory(self, *args, **kwargs):
        """BUG: 内存分配不做分页，连续分配碎片多"""
        return None

    def read_write_file(self, *args, **kwargs):
        """BUG: 文件系统不做inode，文件名直接存数据"""
        return None

    def handle_interrupt(self, *args, **kwargs):
        """BUG: 中断不做优先级，所有中断一样"""
        return None

    def syscall(self, *args, **kwargs):
        """BUG: 系统调用不做参数检查，非法参数也能过"""
        return None

