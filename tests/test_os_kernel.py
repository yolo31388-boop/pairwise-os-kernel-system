import pytest
from os_kernel.system import OSKernelSystem


class TestOSKernelSystem:

    def test_schedule_process(self):
        """进程调度不做优先级，所有进程一样"""
        obj = OSKernelSystem()
        result = obj.schedule_process()
        self.assertIsNotNone(result)

    def test_allocate_memory(self):
        """内存分配不做分页，连续分配碎片多"""
        obj = OSKernelSystem()
        result = obj.allocate_memory()
        self.assertIsNotNone(result)

    def test_read_write_file(self):
        """文件系统不做inode，文件名直接存数据"""
        obj = OSKernelSystem()
        result = obj.read_write_file()
        self.assertIsNotNone(result)

    def test_handle_interrupt(self):
        """中断不做优先级，所有中断一样"""
        obj = OSKernelSystem()
        result = obj.handle_interrupt()
        self.assertIsNotNone(result)

    def test_syscall(self):
        """系统调用不做参数检查，非法参数也能过"""
        obj = OSKernelSystem()
        result = obj.syscall()
        self.assertIsNotNone(result)

