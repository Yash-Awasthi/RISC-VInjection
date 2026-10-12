/* Bare-metal start-up shared by the Spike and QEMU virt test images.  */

	.section .text.init, "ax"
	.globl _start
_start:
	.option push
	.option norelax
	la	gp, __global_pointer$
	.option pop
	la	sp, __stack_top
	la	t0, trap_entry
	csrw	mtvec, t0
	li	t0, (1 << 13)		/* mstatus.FS = initial */
	csrs	mstatus, t0
	call	main
	call	bm_exit
1:	j	1b

/* Record the trap in bm_trap_cause/bm_trap_tval and resume after the
   faulting 4-byte instruction.  */
	.align 2
trap_entry:
	csrr	t0, mcause
	la	t1, bm_trap_cause
	sd	t0, 0(t1)
	csrr	t0, mtval
	la	t1, bm_trap_tval
	sd	t0, 0(t1)
	csrr	t0, mepc
	addi	t0, t0, 4
	csrw	mepc, t0
	mret

	.section .tohost, "aw", @progbits
	.align 6
	.globl tohost
tohost:	.dword 0
	.align 6
	.globl fromhost
fromhost: .dword 0
