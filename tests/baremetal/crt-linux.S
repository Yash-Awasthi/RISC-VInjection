/* Start-up for the Linux user-mode build (qemu-riscv64).  */

	.text
	.globl _start
_start:
	.option push
	.option norelax
	la	gp, __global_pointer$
	.option pop
	call	main
	call	bm_exit
