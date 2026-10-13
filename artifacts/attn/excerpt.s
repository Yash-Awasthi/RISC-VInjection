	.file	"artifacts-full.c"
	.option nopic
	.attribute arch, "rv64i2p1_m2p0_a2p1_f2p2_d2p2_c2p0_zicsr2p0_zifencei2p0_zmmul1p0_zaamo1p0_zalrsc1p0_zca1p0_zcd1p0_xattn1p0"
	.attribute unaligned_access, 0
	.attribute stack_align, 16
	.text
	.align	1
	.globl	mha
	.type	mha, @function
mha:
	addi	sp,sp,-336
	lw	t4,368(sp)
	sd	s6,272(sp)
	lw	s6,360(sp)
	sd	s11,232(sp)
	sd	s7,264(sp)
	divw	s11,s6,t4
	sd	s8,256(sp)
	ld	s7,344(sp)
	ld	s8,336(sp)
	lw	t3,352(sp)
	fmv.s.x	fa5,zero
	sd	s4,288(sp)
	sd	s5,280(sp)
	sd	s9,248(sp)
	sd	s10,240(sp)
	mv	s5,a0
	mv	s4,a1
	mv	s9,a2
	mv	s10,a6
	sd	ra,328(sp)
	sd	s0,320(sp)
	sd	s1,312(sp)
	sd	s2,304(sp)
	sd	s3,296(sp)
	fsd	fs0,216(sp)
	sd	a3,16(sp)
	sd	a4,32(sp)
	sd	a5,40(sp)
	sd	a7,48(sp)
	fcvt.s.w	fa0,s11
	frflags	a4
	flt.s	a5,fa0,fa5
	fsflags	a4
	bne	a5,zero,.L63
	fsqrt.s	fs0,fa0
.L4:
	slli	s0,t3,2
	mul	s1,s6,s0
	sd	t4,64(sp)
	sd	t3,56(sp)
	mv	a0,s1
	call	malloc
	mv	s3,a0
	mv	a0,s1
	call	malloc
	mv	s2,a0
	mv	a0,s1
	call	malloc
	sd	a0,24(sp)
	mv	a0,s1
	call	malloc
	sd	a0,8(sp)
	mv	a0,s0
	call	malloc
	ld	t3,56(sp)
	li	a3,2047
	ld	t4,64(sp)
	addiw	a4,s6,-1
	addiw	a5,t3,-1
	sgtu	a4,a4,a3
	srli	a5,a5,12
	seqz	a5,a5
	seqz	a4,a4
	and	a4,a4,a5
	addiw	a5,t4,-1
	sgtu	a5,a5,a3
	seqz	a5,a5
	and	a5,a5,a4
	mv	s1,a0
	beq	a5,zero,.L5
	mul	a5,s11,t4
	bne	s6,a5,.L6
	lui	a5,%hi(.LC1)
	flw	fa5,%lo(.LC1)(a5)
	ld	a4,16(sp)
	li	a5,3
	fdiv.s	fa5,fa5,fs0
	sd	a4,136(sp)
	ld	a4,32(sp)
	sd	a5,104(sp)
	sd	s9,128(sp)
	sd	a4,144(sp)
	ld	a4,40(sp)
	sd	s10,160(sp)
	sd	s8,176(sp)
	sd	a4,152(sp)
	ld	a4,48(sp)
	sd	s7,184(sp)
	sw	t3,88(sp)
	sd	a4,168(sp)
	sw	s6,92(sp)
	sw	t4,96(sp)
	sw	zero,100(sp)
	sw	zero,116(sp)
	sd	zero,120(sp)
	addi	a5,sp,88
	fsw	fa5,112(sp)
	addi	a4,sp,128
	attn	s5,s4,a4,a5
.L7:
	mv	a0,s3
	call	free
	mv	a0,s2
	call	free
	ld	a0,24(sp)
	call	free
	ld	a0,8(sp)
	call	free
	ld	s0,320(sp)
	ld	ra,328(sp)
	ld	s2,304(sp)
	ld	s3,296(sp)
	ld	s4,288(sp)
	ld	s5,280(sp)
	ld	s6,272(sp)
	ld	s7,264(sp)
	ld	s8,256(sp)
	ld	s9,248(sp)
	ld	s10,240(sp)
	ld	s11,232(sp)
	fld	fs0,216(sp)
	mv	a0,s1
	ld	s1,312(sp)
	addi	sp,sp,336
	tail	free
.L5:
	ble	t3,zero,.L8
.L6:
	slli	a3,s6,2
	li	a4,0
	li	t0,0
	ble	s6,zero,.L10
.L13:
	add	a1,s6,a4
	slli	t5,a4,2
	slli	a1,a1,2
	add	t1,s3,t5
	add	a1,a1,s4
	add	t5,s4,t5
	mv	a7,s10
	mv	a6,s9
	li	a0,0
.L15:
	fmv.s.x	fa5,zero
	mv	a2,a6
	mv	a5,t5
.L11:
	flw	fa3,0(a5)
	flw	fa4,0(a2)
	addi	a5,a5,4
	add	a2,a2,a3
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a5,a1,.L11
	flw	fa4,0(a7)
	addiw	a0,a0,1
	addi	a6,a6,4
	fadd.s	fa5,fa4,fa5
	addi	a7,a7,4
	addi	t1,t1,4
	fsw	fa5,-4(t1)
	bne	s6,a0,.L15
	addiw	t0,t0,1
	addw	a4,a4,s6
	bne	t3,t0,.L13
	li	a4,0
	li	t0,0
.L14:
	add	a1,s6,a4
	ld	a7,48(sp)
	ld	a6,16(sp)
	slli	t5,a4,2
	slli	a1,a1,2
	add	t1,s2,t5
	add	a1,a1,s4
	add	t5,s4,t5
	li	a0,0
.L19:
	fmv.s.x	fa5,zero
	mv	a2,a6
	mv	a5,t5
.L16:
	flw	fa3,0(a5)
	flw	fa4,0(a2)
	addi	a5,a5,4
	add	a2,a2,a3
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a5,a1,.L16
	flw	fa4,0(a7)
	addiw	a0,a0,1
	addi	a6,a6,4
	fadd.s	fa5,fa4,fa5
	addi	a7,a7,4
	addi	t1,t1,4
	fsw	fa5,-4(t1)
	bne	s6,a0,.L19
	addiw	t0,t0,1
	addw	a4,a4,s6
	bne	t3,t0,.L14
	li	t2,0
	li	t0,0
.L18:
	ld	a5,24(sp)
	add	a2,s6,t0
	ld	a0,32(sp)
	slli	t1,t0,2
	slli	a2,a2,2
	add	a7,a5,t1
	add	a2,a2,s4
	add	t1,t1,s4
	mv	a6,s8
	li	a1,0
.L22:
	fmv.s.x	fa5,zero
	mv	a4,a0
	mv	a5,t1
.L20:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	add	a4,a4,a3
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a2,a5,.L20
	flw	fa4,0(a6)
	addiw	a1,a1,1
	addi	a0,a0,4
	fadd.s	fa5,fa4,fa5
	addi	a6,a6,4
	addi	a7,a7,4
	fsw	fa5,-4(a7)
	bne	s6,a1,.L22
	addiw	t2,t2,1
	addw	t0,t0,s6
	bne	t3,t2,.L18
.L10:
	ble	t4,zero,.L24
.L23:
	fsd	fs1,208(sp)
	fsd	fs2,200(sp)
	fsd	fs3,192(sp)
	li	s4,0
	li	a0,0
.L25:
	bgt	t3,zero,.L71
	addiw	a0,a0,1
	addw	s4,s4,s11
	bgt	t4,a0,.L25
	fld	fs1,208(sp)
	fld	fs2,200(sp)
	fld	fs3,192(sp)
	ble	t3,zero,.L7
.L24:
	slli	a2,s6,2
	li	t5,0
	li	t6,0
	ble	s6,zero,.L7
	ld	t4,8(sp)
.L44:
	add	a3,s6,t5
	ld	a0,40(sp)
	slli	t1,t5,2
	slli	a3,a3,2
	add	a7,s5,t1
	add	a3,t4,a3
	add	t1,t4,t1
	mv	a6,s7
	li	a1,0
.L45:
	fmv.s.x	fa5,zero
	mv	a4,a0
	mv	a5,t1
.L42:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	add	a4,a4,a2
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a3,a5,.L42
	flw	fa4,0(a6)
	addiw	a1,a1,1
	addi	a0,a0,4
	fadd.s	fa5,fa4,fa5
	addi	a6,a6,4
	addi	a7,a7,4
	fsw	fa5,-4(a7)
	bne	s6,a1,.L45
	addiw	t6,t6,1
	addw	t5,s6,t5
	bne	t3,t6,.L44
	j	.L7
.L71:
	lui	a5,%hi(.LC1)
	flw	fs1,%lo(.LC1)(a5)
	addi	s0,s0,4
	lui	a5,%hi(.LC0)
	fdiv.s	fs1,fs1,fs0
	flw	fs2,%lo(.LC0)(a5)
	add	a5,s1,s0
	mv	s9,s11
	sd	a5,16(sp)
	sd	a0,32(sp)
	sd	s5,48(sp)
	sd	s7,56(sp)
	sd	t3,64(sp)
	sd	t4,72(sp)
	slli	s11,s6,2
.L37:
	ld	a5,24(sp)
	slli	s7,s4,2
	addi	s10,s1,4
	add	s7,a5,s7
	mv	s5,s4
.L40:
	add	a2,s9,s5
	fmv.s	fa2,fs2
	slli	a2,a2,2
	slli	s0,s5,2
	add	a2,s3,a2
	add	t1,s3,s0
	mv	a6,s4
	mv	a0,s1
.L36:
	slli	a4,a6,2
	fmv.s.x	fa5,zero
	add	a4,s2,a4
	mv	a5,t1
	ble	s9,zero,.L31
.L26:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	addi	a4,a4,4
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a2,a5,.L26
.L31:
	fmul.s	fa5,fs1,fa5
	fmv.s	fs0,fa2
	fgt.s	a5,fa5,fa2
	fsw	fa5,0(a0)
	beq	a5,zero,.L28
	fmv.s	fs0,fa5
.L28:
	addi	a0,a0,4
	fmv.s	fa2,fs0
	addw	a6,a6,s6
	bne	s10,a0,.L36
	fmv.s.x	fs3,zero
	mv	s8,s1
.L29:
	flw	fa0,0(s8)
	addi	s8,s8,4
	fsub.s	fa0,fa0,fs0
	call	expf
	fsw	fa0,-4(s8)
	fadd.s	fs3,fs3,fa0
	bne	s10,s8,.L29
	ble	s9,zero,.L32
	ld	a5,8(sp)
	mv	a0,s7
	li	a2,0
	add	s0,a5,s0
.L33:
	fmv.s.x	fa5,zero
	mv	a4,a0
	mv	a5,s1
.L34:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	add	a4,a4,s11
	fmadd.s	fa5,fa3,fa4,fa5
	bne	s10,a5,.L34
	fdiv.s	fa5,fa5,fs3
	addiw	a2,a2,1
	addi	a0,a0,4
	addi	s0,s0,4
	fsw	fa5,-4(s0)
	bne	s9,a2,.L33
.L32:
	ld	a5,16(sp)
	addi	s10,s10,4
	addw	s5,s5,s6
	bne	a5,s10,.L40
	ld	a5,32(sp)
	ld	a4,72(sp)
	addw	s4,s9,s4
	addiw	a5,a5,1
	sd	a5,32(sp)
	bgt	a4,a5,.L37
	ld	t3,64(sp)
	ld	s5,48(sp)
	ld	s7,56(sp)
	fld	fs1,208(sp)
	fld	fs2,200(sp)
	fld	fs3,192(sp)
	bgt	t3,zero,.L24
	j	.L7
.L8:
	bgt	t4,zero,.L23
	j	.L7
.L63:
	sd	t4,24(sp)
	sd	t3,8(sp)
	call	sqrtf
	fmv.s	fs0,fa0
	ld	t4,24(sp)
	ld	t3,8(sp)
	j	.L4
	.size	mha, .-mha
	.section	.srodata.cst4,"aM",@progbits,4
	.align	2
.LC0:
	.word	-8388608
	.align	2
.LC1:
	.word	1065353216
	.ident	"GCC: (GNU) 16.2.1 20261012"
	.section	.note.GNU-stack,"",@progbits
