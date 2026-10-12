OUTPUT_ARCH(riscv)
ENTRY(_start)
SECTIONS
{
  . = 0x80000000;
  .text.init : { *(.text.init) }
  .tohost : { *(.tohost) }
  .text : { *(.text*) }
  .rodata : { *(.rodata*) *(.srodata*) }
  .data : { *(.data*) }
  __global_pointer$ = . + 0x800;
  .sdata : { *(.sdata*) }
  .bss : { *(.sbss*) *(.bss*) *(COMMON) }
  . = ALIGN(16);
  . += 0x40000;
  __stack_top = .;
  __heap_start = .;
}
