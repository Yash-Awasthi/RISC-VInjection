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
	addi	sp,sp,-224
	sd	s0,208(sp)
	sd	s6,160(sp)
	lw	s0,256(sp)
	lw	s6,248(sp)
	sd	s11,120(sp)
	sd	s7,152(sp)
	divw	s11,s6,s0
	sd	s8,144(sp)
	ld	s7,232(sp)
	ld	s8,224(sp)
	lw	t3,240(sp)
	fmv.s.x	fa5,zero
	sd	s5,168(sp)
	sd	s9,136(sp)
	sd	s10,128(sp)
	mv	s9,a1
	mv	s5,a4
	mv	s10,a5
	sd	ra,216(sp)
	sd	s1,200(sp)
	sd	s2,192(sp)
	sd	s3,184(sp)
	sd	s4,176(sp)
	fsd	fs0,104(sp)
	sd	s0,24(sp)
	sd	a0,48(sp)
	sd	a2,8(sp)
	sd	a3,16(sp)
	sd	a6,40(sp)
	sd	a7,56(sp)
	fcvt.s.w	fa0,s11
	frflags	a4
	flt.s	a5,fa0,fa5
	fsflags	a4
	bne	a5,zero,.L61
	fsqrt.s	fs0,fa0
.L4:
	slli	s3,t3,2
	mul	s0,s6,s3
	sd	t3,64(sp)
	mv	a0,s0
	call	malloc
	mv	s2,a0
	mv	a0,s0
	call	malloc
	mv	s1,a0
	mv	a0,s0
	call	malloc
	sd	a0,32(sp)
	mv	a0,s0
	call	malloc
	mv	s4,a0
	mv	a0,s3
	call	malloc
	ld	t3,64(sp)
	mv	s0,a0
	ble	t3,zero,.L5
	slli	a3,s6,2
	li	a4,0
	li	t5,0
	ble	s6,zero,.L7
.L10:
	add	a1,s6,a4
	ld	a7,40(sp)
	ld	a6,8(sp)
	slli	t4,a4,2
	slli	a1,a1,2
	add	t1,s2,t4
	add	a1,s9,a1
	add	t4,s9,t4
	li	a0,0
.L12:
	fmv.s.x	fa5,zero
	mv	a2,a6
	mv	a5,t4
.L8:
	flw	fa3,0(a5)
	flw	fa4,0(a2)
	addi	a5,a5,4
	add	a2,a2,a3
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a5,a1,.L8
	flw	fa4,0(a7)
	addiw	a0,a0,1
	addi	a6,a6,4
	fadd.s	fa5,fa4,fa5
	addi	a7,a7,4
	addi	t1,t1,4
	fsw	fa5,-4(t1)
	bne	s6,a0,.L12
	addiw	t5,t5,1
	addw	a4,a4,s6
	bne	t3,t5,.L10
	li	a4,0
	li	t5,0
.L11:
	add	a1,s6,a4
	ld	a7,56(sp)
	ld	a6,16(sp)
	slli	t4,a4,2
	slli	a1,a1,2
	add	t1,s1,t4
	add	a1,s9,a1
	add	t4,s9,t4
	li	a0,0
.L16:
	fmv.s.x	fa5,zero
	mv	a2,a6
	mv	a5,t4
.L13:
	flw	fa3,0(a5)
	flw	fa4,0(a2)
	addi	a5,a5,4
	add	a2,a2,a3
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a1,a5,.L13
	flw	fa4,0(a7)
	addiw	a0,a0,1
	addi	a6,a6,4
	fadd.s	fa5,fa4,fa5
	addi	a7,a7,4
	addi	t1,t1,4
	fsw	fa5,-4(t1)
	bne	s6,a0,.L16
	addiw	t5,t5,1
	addw	a4,a4,s6
	bne	t3,t5,.L11
	li	t6,0
	li	t5,0
.L15:
	ld	a5,32(sp)
	add	a2,s6,t5
	slli	t1,t5,2
	slli	a2,a2,2
	add	a7,a5,t1
	add	a2,s9,a2
	add	t1,s9,t1
	mv	a6,s8
	mv	a0,s5
	li	a1,0
.L19:
	fmv.s.x	fa5,zero
	mv	a4,a0
	mv	a5,t1
.L17:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	add	a4,a4,a3
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a2,a5,.L17
	flw	fa4,0(a6)
	addiw	a1,a1,1
	addi	a0,a0,4
	fadd.s	fa5,fa4,fa5
	addi	a6,a6,4
	addi	a7,a7,4
	fsw	fa5,-4(a7)
	bne	s6,a1,.L19
	addiw	t6,t6,1
	addw	t5,t5,s6
	bne	t6,t3,.L15
.L7:
	ld	a5,24(sp)
	ble	a5,zero,.L22
.L20:
	fsd	fs1,96(sp)
	fsd	fs2,88(sp)
	fsd	fs3,80(sp)
	li	s9,0
	li	a0,0
.L23:
	bgt	t3,zero,.L69
	ld	a5,24(sp)
	addiw	a0,a0,1
	addw	s9,s9,s11
	bgt	a5,a0,.L23
	fld	fs1,96(sp)
	fld	fs2,88(sp)
	fld	fs3,80(sp)
	ble	t3,zero,.L21
.L22:
	slli	a2,s6,2
	li	t5,0
	li	t6,0
	ble	s6,zero,.L21
.L42:
	ld	a5,48(sp)
	add	a3,s6,t5
	slli	t1,t5,2
	slli	a3,a3,2
	add	a7,a5,t1
	add	a3,s4,a3
	add	t1,s4,t1
	mv	a6,s7
	mv	a0,s10
	li	a1,0
.L43:
	fmv.s.x	fa5,zero
	mv	a4,a0
	mv	a5,t1
.L40:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	add	a4,a4,a2
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a3,a5,.L40
	flw	fa4,0(a6)
	addiw	a1,a1,1
	addi	a0,a0,4
	fadd.s	fa5,fa4,fa5
	addi	a6,a6,4
	addi	a7,a7,4
	fsw	fa5,-4(a7)
	bne	s6,a1,.L43
	addiw	t6,t6,1
	addw	t5,t5,s6
	bne	t3,t6,.L42
.L21:
	mv	a0,s2
	call	free
	mv	a0,s1
	call	free
	ld	a0,32(sp)
	call	free
	mv	a0,s4
	call	free
	mv	a0,s0
	ld	s0,208(sp)
	ld	ra,216(sp)
	ld	s1,200(sp)
	ld	s2,192(sp)
	ld	s3,184(sp)
	ld	s4,176(sp)
	ld	s5,168(sp)
	ld	s6,160(sp)
	ld	s7,152(sp)
	ld	s8,144(sp)
	ld	s9,136(sp)
	ld	s10,128(sp)
	ld	s11,120(sp)
	fld	fs0,104(sp)
	addi	sp,sp,224
	tail	free
.L69:
	lui	a5,%hi(.LC1)
	flw	fs1,%lo(.LC1)(a5)
	addi	s3,s3,4
	lui	a5,%hi(.LC0)
	fdiv.s	fs1,fs1,fs0
	flw	fs2,%lo(.LC0)(a5)
	add	a5,s0,s3
	sd	s10,72(sp)
	sd	a5,8(sp)
	mv	s10,s11
	sd	a0,40(sp)
	sd	s7,56(sp)
	sd	t3,64(sp)
	slli	s11,s6,2
	mv	s5,s4
.L35:
	ld	a5,32(sp)
	slli	s8,s9,2
	addi	s4,s0,4
	add	a5,a5,s8
	sd	a5,16(sp)
	mv	s7,s9
.L38:
	add	a2,s10,s7
	fmv.s	fa2,fs2
	slli	a2,a2,2
	slli	s3,s7,2
	add	a2,s2,a2
	add	t1,s2,s3
	mv	a6,s9
	mv	a0,s0
.L34:
	slli	a4,a6,2
	fmv.s.x	fa5,zero
	add	a4,s1,a4
	mv	a5,t1
	ble	s10,zero,.L29
.L24:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	addi	a4,a4,4
	fmadd.s	fa5,fa3,fa4,fa5
	bne	a2,a5,.L24
.L29:
	fmul.s	fa5,fs1,fa5
	fmv.s	fs0,fa2
	fgt.s	a5,fa5,fa2
	fsw	fa5,0(a0)
	beq	a5,zero,.L26
	fmv.s	fs0,fa5
.L26:
	addi	a0,a0,4
	fmv.s	fa2,fs0
	addw	a6,a6,s6
	bne	s4,a0,.L34
	fmv.s.x	fs3,zero
	mv	s8,s0
.L27:
	flw	fa0,0(s8)
	addi	s8,s8,4
	fsub.s	fa0,fa0,fs0
	call	expf
	fsw	fa0,-4(s8)
	fadd.s	fs3,fs3,fa0
	bne	s4,s8,.L27
	ble	s10,zero,.L30
	ld	a0,16(sp)
	add	s3,s5,s3
	li	a2,0
.L31:
	fmv.s.x	fa5,zero
	mv	a4,a0
	mv	a5,s0
.L32:
	flw	fa3,0(a5)
	flw	fa4,0(a4)
	addi	a5,a5,4
	add	a4,a4,s11
	fmadd.s	fa5,fa3,fa4,fa5
	bne	s4,a5,.L32
	fdiv.s	fa5,fa5,fs3
	addiw	a2,a2,1
	addi	a0,a0,4
	addi	s3,s3,4
	fsw	fa5,-4(s3)
	bne	s10,a2,.L31
.L30:
	ld	a5,8(sp)
	addi	s4,s4,4
	addw	s7,s7,s6
	bne	a5,s4,.L38
	ld	a5,40(sp)
	ld	a4,24(sp)
	addw	s9,s10,s9
	addiw	a5,a5,1
	sd	a5,40(sp)
	blt	a5,a4,.L35
	ld	t3,64(sp)
	ld	s7,56(sp)
	ld	s10,72(sp)
	fld	fs1,96(sp)
	fld	fs2,88(sp)
	fld	fs3,80(sp)
	mv	s4,s5
	bgt	t3,zero,.L22
	j	.L21
.L5:
	ld	a5,24(sp)
	bgt	a5,zero,.L20
	j	.L21
.L61:
	sd	t3,32(sp)
	call	sqrtf
	fmv.s	fs0,fa0
	ld	t3,32(sp)
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
