### AnyKernel3 Ramdisk Mod Script
## osm0sis @ xda-developers
## 一加平板 Pro：GKI 2.0 设备，内核在 boot 分区，ramdisk 在 init_boot 分区，只替换 boot 里的内核

### AnyKernel setup
# global properties
properties() { '
kernel.string=OnePlus Pad Pro GKI
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; } # end properties


### AnyKernel install
# boot shell variables
BLOCK=boot;
IS_SLOT_DEVICE=auto;
RAMDISK_COMPRESSION=auto;
PATCH_VBMETA_FLAG=auto;

# import functions/variables and setup patching - see for reference (DO NOT REMOVE)
. tools/ak3-core.sh;

# boot install
split_boot; # boot 里没有 ramdisk，不解包
flash_boot; # 刷入当前活动槽位
## end boot install
