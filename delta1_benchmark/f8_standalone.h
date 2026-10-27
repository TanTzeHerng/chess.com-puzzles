// license:BSD-3-Clause
// F8 CPU implementation derived from MAME, copyright Juergen Buchmueller.
// Standalone Delta-1 hardware adapter: generated for the user's isolated fast build.
#include <cstdint>
#include <cstring>
#include <array>
#include <string>
#include <vector>
#include <iostream>
#include <fstream>
#include <iomanip>
#include <chrono>
#include <algorithm>
#include <stdexcept>
using u8=uint8_t;using u16=uint16_t;using u32=uint32_t;using s8=int8_t;
#include "original_rom.inc"
static constexpr u8 S=1,C=2,Z=4,O=8,I=16;
static constexpr int cS=4,cL=6;
struct F8 {
 u16 m_pc0=0,m_pc1=0,m_dc0=0,m_dc1=0;
 u8 m_a=0,m_w=0,m_is=0,m_dbus=0;
 u16 m_io=0,m_irq_vector=0,m_debug_pc=0;
 int m_icount=0,m_irq_request=0,step_icount=0;
 std::array<u8,4096> rom{};
 std::array<u8,256> ram{};
 std::array<u8,64> regs{};
 std::array<u8,5> keys{};
 uint64_t cycles=0,instructions=0,illegal_count=0,irq_count=0;
 mutable uint64_t table_read_count=0,table_write_count=0;
 mutable uint64_t table_read_hash=0;
 uint64_t timer_next=UINT64_MAX;
 std::array<int,256> timer_cycles{};
 u16 smi_vector=0;bool timer_enabled=false,ext_enabled=false,irq_pending=false;
 u8 mux=0,seg=0;bool rc=false;
 std::array<u8,4> digit_value{};
 std::array<uint64_t,4> digit_time{};
 uint64_t display_cycle=0;
 explicit F8(const std::string& path) {
   if(path=="@embedded")rom=embedded_rom;
   else {std::ifstream f(path,std::ios::binary);f.read((char*)rom.data(),4096);
   if(f.gcount()!=4096)throw std::runtime_error("Original 4096-byte ROM required");}
   uint32_t rng=0x9d14abd7;
   for(auto &x:ram){rng=1664525*rng+1013904223;x=u8(rng>>16);}
   timer_cycles[255]=255;u8 r=254;
   for(int n=254;n>=0;--n){timer_cycles[r]=n;r=u8((r<<1)|(((r>>7)^(r>>5)^(r>>4)^(r>>3)^1)&1));}
   reset();
 }
 uint64_t now()const{return cycles+uint64_t(step_icount-m_icount);}
 inline u8 read_mem(u16 a)const{
   if((a&0x3fc0)==0x2bc0) {++table_read_count;table_read_hash=(table_read_hash*33u)^(a&255);}
   return (a&0x2000)?ram[a&255]:rom[a&4095];
 }
 inline void write_mem(u16 a,u8 v){if((a&0x3fc0)==0x2bc0)++table_write_count;if(a&0x2000)ram[a&255]=v;}
 inline u8 read_reg(u8 a)const{return regs[a&63];}
 inline void write_reg(u8 a,u8 v){regs[a&63]=v;}
 void refresh_display(){
   const uint64_t t=now();
   unsigned select=(1u<<((~mux)&7))>>4;
   bool blank=rc&&((display_cycle/400000)&1);
   if(t-display_cycle>=64)for(int d=0;d<4;++d)if(select&(1<<d)){
     digit_value[d]=blank?0:seg;digit_time[d]=t;
   }
   display_cycle=t;
 }

 u8 read_io(u8 a){
   if(a==0){u8 v=0;unsigned in=((1u<<((~mux)&7))>>3)&31;
    for(int n=0;n<5;++n)if(in&(1<<n))v|=keys[n];return u8((v<<4)|mux|8);}
   if(a==12)return smi_vector>>8;
   if(a==13)return smi_vector&255;
   if(a==14||a==15)return 0;
   return 255;
 }
 void write_io(u8 a,u8 v){
   if(a==0){refresh_display();mux=v;}
   else if(a==1){refresh_display();rc=(v&128)!=0;seg=0;for(int k=0;k<7;++k)seg|=((v>>k)&1)<<(6-k);}
   else if(a==12)smi_vector=(u16(v)<<8)|(smi_vector&255);
   else if(a==13)smi_vector=(smi_vector&0xff00)|v;
   else if(a==14){ext_enabled=(v&3)==1;timer_enabled=(v&3)==3;m_irq_request=irq_pending;}
   else if(a==15){irq_pending=false;m_irq_request=0;timer_next=v==255?UINT64_MAX:now()+31ull*timer_cycles[v];}
 }
 u16 ack_irq(){irq_pending=false;m_irq_request=0;++irq_count;return smi_vector&0xff7f;}
 void advance(int n){
   cycles+=n;
   while(timer_next!=UINT64_MAX&&cycles>=timer_next){
     if(timer_enabled){irq_pending=true;m_irq_request=1;}timer_next+=31*255;
   }
 }
 void reset(){
   smi_vector=0;timer_enabled=ext_enabled=irq_pending=false;m_irq_request=0;
   step_icount=m_icount=0;write_io(15,0);
   ROMC_08();m_w&=~I;ROMC_00(cS);step_icount=m_icount;
 }
 void run(uint64_t n){
   uint64_t target=cycles+n;
   while(cycles<target){m_icount=int(std::min<uint64_t>(target-cycles,10000000));step_icount=m_icount;execute_run();}
   step_icount=m_icount;
 }
 std::array<u8,4> digits()const{
   std::array<u8,4> d{};for(int n=0;n<4;++n)if(cycles-digit_time[3-n]<45000)d[n]=digit_value[3-n];return d;
 }
 std::string display()const{
   std::string s;for(auto v:digits()){
    const int val[]={63,6,91,79,102,109,125,7,127,103};char c='?';
    for(int n=0;n<10;++n)if(v==val[n])c='0'+n;
    const int xv[]={119,124,57,94,121,113,61,118};for(int n=0;n<8;++n)if(v==xv[n])c='a'+n;
    if(v==0)c=' ';s+=c;
   }return s;
 }
 void press(int port,int mask,double seconds=0.5){keys[port]|=mask;run(uint64_t(seconds*2.0/3*2000000));keys[port]&=~mask;run(uint64_t(seconds/3*2000000));}
 void digit(int n){if(n==0)press(3,2);else if(n<=4)press(1,1<<(n-1));else if(n<=8)press(2,1<<(n-5));else if(n==9)press(3,1);}
 void level(std::string s){s=std::string(6-s.size(),'0')+s;press(0,2);run(1000000);for(char c:s)digit(c-'0');press(4,8);run(1000000);}
 void move(std::string m){for(char c:m.substr(0,4))digit(c>='a'?c-'a'+1:c-'0');press(4,8);run(500000);}
 void execute_run();
	inline void CLR_OZCS();
	inline void SET_SZ(u8 n);
	inline u8 do_add(u8 n, u8 m, u8 c = 0);
	inline u8 do_add_decimal(u8 augend, u8 addend);

	void ROMC_00(int insttim);
	void ROMC_01();
	void ROMC_02();
	void ROMC_03(int insttim);
	void ROMC_04();
	void ROMC_05();
	void ROMC_06();
	void ROMC_07();
	void ROMC_08();
	void ROMC_09();
	void ROMC_0A();
	void ROMC_0B();
	void ROMC_0C();
	void ROMC_0D();
	void ROMC_0E();
	void ROMC_0F();
	void ROMC_10();
	void ROMC_11();
	void ROMC_12();
	void ROMC_13();
	void ROMC_14();
	void ROMC_15();
	void ROMC_16();
	void ROMC_17();
	void ROMC_18();
	void ROMC_19();
	void ROMC_1A();
	void ROMC_1B();
	void ROMC_1C(int insttim);
	void ROMC_1D();
	void ROMC_1E();
	void ROMC_1F();
	void illegal();
	void f8_lr_a_ku();
	void f8_lr_a_kl();
	void f8_lr_a_qu();
	void f8_lr_a_ql();
	void f8_lr_ku_a();
	void f8_lr_kl_a();
	void f8_lr_qu_a();
	void f8_lr_ql_a();
	void f8_lr_k_p();
	void f8_lr_p_k();
	void f8_lr_a_is();
	void f8_lr_is_a();
	void f8_pk();
	void f8_lr_p0_q();
	void f8_lr_q_dc();
	void f8_lr_dc_q();
	void f8_lr_dc_h();
	void f8_lr_h_dc();
	void f8_sr_1();
	void f8_sl_1();
	void f8_sr_4();
	void f8_sl_4();
	void f8_lm();
	void f8_st();
	void f8_com();
	void f8_lnk();
	void f8_di();
	void f8_ei();
	void f8_pop();
	void f8_lr_w_j();
	void f8_lr_j_w();
	void f8_inc();
	void f8_li();
	void f8_ni();
	void f8_oi();
	void f8_xi();
	void f8_ai();
	void f8_ci();
	void f8_in();
	void f8_out();
	void f8_pi();
	void f8_jmp();
	void f8_dci();
	void f8_nop();
	void f8_xdc();
	void f8_ds_r(int r);
	void f8_ds_isar();
	void f8_ds_isar_i();
	void f8_ds_isar_d();
	void f8_lr_a_r(int r);
	void f8_lr_a_isar();
	void f8_lr_a_isar_i();
	void f8_lr_a_isar_d();
	void f8_lr_r_a(int r);
	void f8_lr_isar_a();
	void f8_lr_isar_i_a();
	void f8_lr_isar_d_a();
	void f8_lisu(int e);
	void f8_lisl(int e);
	void f8_lis(int i);
	void f8_bt(int e);
	void f8_am();
	void f8_amd();
	void f8_nm();
	void f8_om();
	void f8_xm();
	void f8_cm();
	void f8_adc();
	void f8_br7();
	void f8_bf(int t);
	void f8_ins_0(int n);
	void f8_ins_1(int n);
	void f8_outs_0(int n);
	void f8_outs_1(int n);
	void f8_as(int r);
	void f8_as_isar();
	void f8_as_isar_i();
	void f8_as_isar_d();
	void f8_asd(int r);
	void f8_asd_isar();
	void f8_asd_isar_i();
	void f8_asd_isar_d();
	void f8_xs(int r);
	void f8_xs_isar();
	void f8_xs_isar_i();
	void f8_xs_isar_d();
	void f8_ns(int r);
	void f8_ns_isar();
	void f8_ns_isar_i();
	void f8_ns_isar_d();
};
inline void F8::CLR_OZCS()
{
	m_w &= ~(O|Z|C|S);
}

/* set sign and zero flags (note: the S flag is complementary) */
inline void F8::SET_SZ(u8 n)
{
	if (n == 0)
		m_w |= Z;
	if (~n & 0x80)
		m_w |= S;
}

/* set overflow and carry flags */
inline u8 F8::do_add(u8 n, u8 m, u8 c)
{
	u16 r = n + m + c;
	if (r & 0x100)
		m_w |= C;
	if ((n^r) & (m^r) & 0x80)
		m_w |= O;

	return r & 0xff;
}

/* decimal add helper */
inline u8 F8::do_add_decimal(u8 augend, u8 addend)
{
	/* From F8 Guide To programming description of AMD
	 * binary add the addend to the binary sum of the augend and $66
	 * *NOTE* the binary addition of the augend to $66 is done before AMD is called
	 * record the status of the carry and intermediate carry
	 * add a factor to the sum based on the carry and intermediate carry:
	 * - no carry, no intermediate carry, add $AA
	 * - no carry, intermediate carry, add $A0
	 * - carry, no intermediate carry, add $0A
	 * - carry, intermediate carry, add $00
	 * any carry from the low-order digit is suppressed
	 * *NOTE* status flags are updated prior to the factor being added
	 */
	u8 tmp = augend + addend;

	u8 c = 0; // high order carry
	u8 ic = 0; // low order carry

	if (((augend + addend) & 0xff0) > 0xf0)
		c = 1;
	if ((augend & 0x0f) + (addend & 0x0f) > 0x0F)
		ic = 1;

	CLR_OZCS();
	do_add(augend,addend);
	SET_SZ(tmp);

	if (c == 0 && ic == 0)
		tmp = ((tmp + 0xa0) & 0xf0) + ((tmp + 0x0a) & 0x0f);
	if (c == 0 && ic == 1)
		tmp = ((tmp + 0xa0) & 0xf0) + (tmp & 0x0f);
	if (c == 1 && ic == 0)
		tmp = (tmp & 0xf0) + ((tmp + 0x0a) & 0x0f);

	return tmp;
}


/******************************************************************************
 * ROMC (ROM cycles)
 * This is what the Fairchild F8 CPUs use instead of an address bus
 * There are 5 control lines and each combination of those lines has
 * a special meaning. The devices attached to those control lines all
 * have their own program counters (PC0 and PC1) and at least one
 * data counter (DC0).
 * Currently the emulation does not handle distinct PCs and DCs, but
 * only one instance inside the CPU context.
 ******************************************************************************/
__attribute__((always_inline)) inline void F8::ROMC_00(int insttim)
{
	/*
	 * Instruction Fetch. The device whose address space includes the
	 * contents of the PC0 register must place on the data bus the op
	 * code addressed by PC0; then all devices increment the contents
	 * of PC0.
	 */
	m_dbus = rom[m_pc0 & 4095];
	m_pc0 += 1;
	m_icount -= insttim; /* ROMC00 is usually short, not short+long, but DS is long */
}

__attribute__((always_inline)) inline void F8::ROMC_01()
{
	/*
	 * The device whose address space includes the contents of the PC0
	 * register must place on the data bus the contents of the memory
	 * location addressed by PC0; then all devices add the 8-bit value
	 * on the data bus as signed binary number to PC0.
	 */
	m_dbus = rom[m_pc0 & 4095];
	m_pc0 += (s8)m_dbus;
	m_icount -= cL;
}

__attribute__((always_inline)) inline void F8::ROMC_02()
{
	/*
	 * The device whose DC0 addresses a memory word within the address
	 * space of that device must place on the data bus the contents of
	 * the memory location addressed by DC0; then all devices increment
	 * DC0.
	 */
	m_dbus = read_mem(m_dc0);
	m_dc0 += 1;
	m_icount -= cL;
}

__attribute__((always_inline)) inline void F8::ROMC_03(int insttim)
{
	/*
	 * Similiar to 0x00, except that it is used for immediate operands
	 * fetches (using PC0) instead of instruction fetches.
	 */
	m_dbus = m_io = rom[m_pc0 & 4095];
	m_pc0 += 1;
	m_icount -= insttim;
}

void F8::ROMC_04()
{
	/*
	 * Copy the contents of PC1 into PC0
	 */
	m_pc0 = m_pc1;
	m_icount -= cS;
}

void F8::ROMC_05()
{
	/*
	 * Store the data bus contents into the memory location pointed
	 * to by DC0; increment DC0.
	 */
	write_mem(m_dc0, m_dbus);
	m_dc0 += 1;
	m_icount -= cL;
}

void F8::ROMC_06()
{
	/*
	 * Place the high order byte of DC0 on the data bus.
	 */
	m_dbus = m_dc0 >> 8;
	m_icount -= cL;
}

void F8::ROMC_07()
{
	/*
	 * Place the high order byte of PC1 on the data bus.
	 */
	m_dbus = m_pc1 >> 8;
	m_icount -= cL;
}

void F8::ROMC_08()
{
	/*
	 * All devices copy the contents of PC0 into PC1. The CPU outputs
	 * zero on the data bus in this ROMC state. Load the data bus into
	 * both halves of PC0, thus clearing the register.
	 */
	m_pc1 = m_pc0;
	m_dbus = 0;
	m_pc0 = 0 * 0x0101;
	m_icount -= cL;
}

void F8::ROMC_09()
{
	/*
	 * The device whose address space includes the contents of the DC0
	 * register must place the low order byte of DC0 onto the data bus.
	 */
	m_dbus = m_dc0 & 0xff;
	m_icount -= cL;
}

void F8::ROMC_0A()
{
	/*
	 * All devices add the 8-bit value on the data bus, treated as
	 * signed binary number, to the data counter.
	 */
	m_dc0 += (s8)m_dbus;
	m_icount -= cL;
}

void F8::ROMC_0B()
{
	/*
	 * The device whose address space includes the value in PC1
	 * must place the low order byte of PC1 onto the data bus.
	 */
	m_dbus = m_pc1 & 0xff;
	m_icount -= cL;
}

void F8::ROMC_0C()
{
	/*
	 * The device whose address space includes the contents of the PC0
	 * register must place the contents of the memory word addressed
	 * by PC0 into the data bus; then all devices move the value that
	 * has just been placed on the data bus into the low order byte of PC0.
	 */
	m_dbus = rom[m_pc0 & 4095];
	m_pc0 = (m_pc0 & 0xff00) | m_dbus;
	m_icount -= cL;
}

void F8::ROMC_0D()
{
	/*
	 * All devices store in PC1 the current contents of PC0, incremented
	 * by 1; PC0 is unaltered.
	 */
	m_pc1 = m_pc0 + 1;
	m_icount -= cS;
}

void F8::ROMC_0E()
{
	/*
	 * The device whose address space includes the contents of the PC0
	 * register must place the word addressed by PC0 into the data bus.
	 * The value on the data bus is then moved to the low order byte
	 * of DC0 by all devices.
	 */
	m_dbus = rom[m_pc0 & 4095];
	m_dc0 = (m_dc0 & 0xff00) | m_dbus;
	m_icount -= cL;
}

void F8::ROMC_0F()
{
	/*
	 * The interrupting device with highest priority must place the
	 * low order byte of the interrupt vector on the data bus.
	 * All devices must copy the contents of PC0 into PC1. All devices
	 * must move the contents of the data bus into the low order
	 * byte of PC0.
	 */
	m_irq_vector = ack_irq();
	m_dbus = m_irq_vector & 0x00ff;
	m_pc1 = m_pc0;
	m_pc0 = (m_pc0 & 0xff00) | m_dbus;
	m_icount -= cL;
}

void F8::ROMC_10()
{
	/*
	 * Inhibit any modification to the interrupt priority logic.
	 */
	// TODO
	m_icount -= cL;
}

void F8::ROMC_11()
{
	/*
	 * The device whose address space includes the contents of PC0
	 * must place the contents of the addressed memory word on the
	 * data bus. All devices must then move the contents of the
	 * data bus to the upper byte of DC0.
	 */
	m_dbus = rom[m_pc0 & 4095];
	m_dc0 = (m_dc0 & 0x00ff) | (m_dbus << 8);
	m_icount -= cL;
}

void F8::ROMC_12()
{
	/*
	 * All devices copy the contents of PC0 into PC1. All devices then
	 * move the contents of the data bus into the low order byte of PC0.
	 */
	m_pc1 = m_pc0;
	m_pc0 = (m_pc0 & 0xff00) | m_dbus;
	m_icount -= cL;
}

void F8::ROMC_13()
{
	/*
	 * The interrupting device with highest priority must move the high
	 * order half of the interrupt vector onto the data bus. All devices
	 * must then move the contents of the data bus into the high order
	 * byte of PC0. The interrupting device resets its interrupt circuitry
	 * (so that it is no longer requesting CPU servicing and can respond
	 * to another interrupt).
	 */
	m_dbus = m_irq_vector >> 8;
	m_pc0 = (m_pc0 & 0x00ff) | (m_dbus << 8);
	m_w&=~I;
	m_icount -= cL;
}

void F8::ROMC_14()
{
	/*
	 * All devices move the contents of the data bus into the high
	 * order byte of PC0.
	 */
	m_pc0 = (m_pc0 & 0x00ff) | (m_dbus << 8);
	m_icount -= cL;
}

void F8::ROMC_15()
{
	/*
	 * All devices move the contents of the data bus into the high
	 * order byte of PC1.
	 */
	m_pc1 = (m_pc1 & 0x00ff) | (m_dbus << 8);
	m_icount -= cL;
}

void F8::ROMC_16()
{
	/*
	 * All devices move the contents of the data bus into the high
	 * order byte of DC0.
	 */
	m_dc0 = (m_dc0 & 0x00ff) | (m_dbus << 8);
	m_icount -= cL;
}

void F8::ROMC_17()
{
	/*
	 * All devices move the contents of the data bus into the low
	 * order byte of PC0.
	 */
	m_pc0 = (m_pc0 & 0xff00) | m_dbus;
	m_icount -= cL;
}

void F8::ROMC_18()
{
	/*
	 * All devices move the contents of the data bus into the low
	 * order byte of PC1.
	 */
	m_pc1 = (m_pc1 & 0xff00) | m_dbus;
	m_icount -= cL;
}

void F8::ROMC_19()
{
	/*
	 * All devices move the contents of the data bus into the low
	 * order byte of DC0.
	 */
	m_dc0 = (m_dc0 & 0xff00) | m_dbus;
	m_icount -= cL;
}

__attribute__((always_inline)) inline void F8::ROMC_1A()
{
	/*
	 * During the prior cycle, an I/O port timer or interrupt control
	 * register was addressed; the device containing the addressed port
	 * must place the contents of the data bus into the address port.
	 */
	write_io(m_io, m_dbus);
	m_icount -= cL;
}

void F8::ROMC_1B()
{
	/*
	 * During the prior cycle, the data bus specified the address of an
	 * I/O port. The device containing the addressed I/O port must place
	 * the contents of the I/O port on the data bus. (Note that the
	 * contents of timer and interrupt control registers cannot be read
	 * back onto the data bus).
	 */
	m_dbus = read_io(m_io);
	m_icount -= cL;
}

__attribute__((always_inline)) inline void F8::ROMC_1C(int insttim)
{
	/*
	 * None.
	 */
	m_icount -= insttim;
}

void F8::ROMC_1D()
{
	/*
	 * Devices with DC0 and DC1 registers must switch registers.
	 * Devices without a DC1 register perform no operation.
	 */
	u16 tmp = m_dc0;
	m_dc0 = m_dc1;
	m_dc1 = tmp;
	m_icount -= cS;
}

void F8::ROMC_1E()
{
	/*
	 * The devices whose address space includes the contents of PC0
	 * must place the low order byte of PC0 onto the data bus.
	 */
	m_dbus = m_pc0 & 0xff;
	m_icount -= cL;
}

void F8::ROMC_1F()
{
	/*
	 * The devices whose address space includes the contents of PC0
	 * must place the high order byte of PC0 onto the data bus.
	 */
	m_dbus = (m_pc0 >> 8) & 0xff;
	m_icount -= cL;
}

/***********************************
 *  illegal opcodes
 ***********************************/
void F8::illegal()
{
 ++illegal_count;
}

/***************************************************
 *  O Z C S 0000 0000
 *  - - - - LR  A,KU
 ***************************************************/
void F8::f8_lr_a_ku()
{
	m_a = read_reg(12);
}

/***************************************************
 *  O Z C S 0000 0001
 *  - - - - LR  A,KL
 ***************************************************/
void F8::f8_lr_a_kl()
{
	m_a = read_reg(13);
}

/***************************************************
 *  O Z C S 0000 0010
 *  - - - - LR  A,QU
 ***************************************************/
void F8::f8_lr_a_qu()
{
	m_a = read_reg(14);
}

/***************************************************
 *  O Z C S 0000 0011
 *  - - - - LR  A,QL
 ***************************************************/
void F8::f8_lr_a_ql()
{
	m_a = read_reg(15);
}

/***************************************************
 *  O Z C S 0000 0100
 *  - - - - LR  KU,A
 ***************************************************/
void F8::f8_lr_ku_a()
{
	write_reg(12, m_a);
}

/***************************************************
 *  O Z C S 0000 0101
 *  - - - - LR  KL,A
 ***************************************************/
void F8::f8_lr_kl_a()
{
	write_reg(13, m_a);
}

/***************************************************
 *  O Z C S 0000 0110
 *  - - - - LR  QU,A
 ***************************************************/
void F8::f8_lr_qu_a()
{
	write_reg(14, m_a);
}

/***************************************************
 *  O Z C S 0000 0111
 *  - - - - LR  QL,A
 ***************************************************/
void F8::f8_lr_ql_a()
{
	write_reg(15, m_a);
}

/***************************************************
 *  O Z C S 0000 1000
 *  - - - - LR  K,P
 ***************************************************/
void F8::f8_lr_k_p()
{
	ROMC_07();
	write_reg(12, m_dbus);
	ROMC_0B();
	write_reg(13, m_dbus);
}

/***************************************************
 *  O Z C S 0000 1001
 *  - - - - LR  P,K
 ***************************************************/
void F8::f8_lr_p_k()
{
	m_dbus = read_reg(12);
	ROMC_15();
	m_dbus = read_reg(13);
	ROMC_18();
}

/***************************************************
 *  O Z C S 0000 1010
 *  - - - - LR  A,IS
 ***************************************************/
void F8::f8_lr_a_is()
{
	m_a = m_is;
}

/***************************************************
 *  O Z C S 0000 1011
 *  - - - - LR  IS,A
 ***************************************************/
void F8::f8_lr_is_a()
{
	m_is = m_a & 0x3f;
}

/***************************************************
 *  O Z C S 0000 1100
 *  - - - - PK
 ***************************************************/
void F8::f8_pk()
{
	m_dbus = read_reg(13);
	ROMC_12();
	m_dbus = read_reg(12);
	ROMC_14();
}

/***************************************************
 *  O Z C S 0000 1101
 *  - - - - LR  P0,Q
 ***************************************************/
void F8::f8_lr_p0_q()
{
	m_dbus = read_reg(15);
	ROMC_17();
	m_dbus = read_reg(14);
	ROMC_14();
}

/***************************************************
 *  O Z C S 0000 1110
 *  - - - - LR   Q,DC
 ***************************************************/
void F8::f8_lr_q_dc()
{
	ROMC_06();
	write_reg(14, m_dbus);
	ROMC_09();
	write_reg(15, m_dbus);
}

/***************************************************
 *  O Z C S 0000 1111
 *  - - - - LR   DC,Q
 ***************************************************/
void F8::f8_lr_dc_q()
{
	m_dbus = read_reg(14);
	ROMC_16();
	m_dbus = read_reg(15);
	ROMC_19();
}

/***************************************************
 *  O Z C S 0001 0000
 *  - - - - LR   DC,H
 ***************************************************/
void F8::f8_lr_dc_h()
{
	m_dbus = read_reg(10);
	ROMC_16();
	m_dbus = read_reg(11);
	ROMC_19();
}

/***************************************************
 *  O Z C S 0001 0001
 *  - - - - LR   H,DC
 ***************************************************/
void F8::f8_lr_h_dc()
{
	ROMC_06();
	write_reg(10, m_dbus);
	ROMC_09();
	write_reg(11, m_dbus);
}

/***************************************************
 *  O Z C S 0001 0010
 *  0 x 0 1 SR   1
 ***************************************************/
void F8::f8_sr_1()
{
	m_a >>= 1;
	CLR_OZCS();
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0001 0011
 *  0 x 0 x SL   1
 ***************************************************/
void F8::f8_sl_1()
{
	m_a <<= 1;
	CLR_OZCS();
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0001 0100
 *  0 x 0 1 SR   4
 ***************************************************/
void F8::f8_sr_4()
{
	m_a >>= 4;
	CLR_OZCS();
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0001 0101
 *  0 x 0 x SL   4
 ***************************************************/
void F8::f8_sl_4()
{
	m_a <<= 4;
	CLR_OZCS();
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0001 0110
 *  - - - - LM
 ***************************************************/
void F8::f8_lm()
{
	ROMC_02();
	m_a = m_dbus;
}

/***************************************************
 *  O Z C S 0001 0111
 *  - - - - ST
 ***************************************************/
void F8::f8_st()
{
	m_dbus = m_a;
	ROMC_05();
}

/***************************************************
 *  O Z C S 0001 1000
 *  0 x 0 x COM
 ***************************************************/
void F8::f8_com()
{
	m_a = ~m_a;
	CLR_OZCS();
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0001 1001
 *  x x x x LNK
 ***************************************************/
void F8::f8_lnk()
{
	bool c = (m_w & C) != 0;
	CLR_OZCS();
	if (c)
		m_a = do_add(m_a,1);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0001 1010
 *          DI
 ***************************************************/
void F8::f8_di()
{
	ROMC_1C(cS);
	m_w &= ~I;
}

/***************************************************
 *  O Z C S 0001 1011
 *          EI
 ***************************************************/
void F8::f8_ei()
{
	ROMC_1C(cS);
	m_w |= I;
}

/***************************************************
 *  O Z C S 0001 1100
 *          POP
 ***************************************************/
void F8::f8_pop()
{
	ROMC_04();
}

/***************************************************
 *  O Z C S 0001 1101
 *  x x x x LR   W,J
 ***************************************************/
void F8::f8_lr_w_j()
{
	ROMC_1C(cS);
	m_w = read_reg(9) & 0x1f;
}

/***************************************************
 *  O Z C S 0001 1110
 *  - - - - LR   J,W
 ***************************************************/
void F8::f8_lr_j_w()
{
	write_reg(9, m_w);
}

/***************************************************
 *  O Z C S 0001 1111
 *  x x x x INC
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_inc()
{
	CLR_OZCS();
	m_a = do_add(m_a,1);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0010 0000   aaaa aaaa
 *  - - - - LI  aa
 ***************************************************/
void F8::f8_li()
{
	ROMC_03(cL);
	m_a = m_dbus;
}

/***************************************************
 *  O Z C S 0010 0001   aaaa aaaa
 *  0 x 0 x NI   aa
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_ni()
{
	ROMC_03(cL);
	CLR_OZCS();
	m_a &= m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0010 0010   aaaa aaaa
 *  0 x 0 x OI   aa
 ***************************************************/
void F8::f8_oi()
{
	ROMC_03(cL);
	CLR_OZCS();
	m_a |= m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0010 0011   aaaa aaaa
 *  0 x 0 x XI   aa
 ***************************************************/
void F8::f8_xi()
{
	ROMC_03(cL);
	CLR_OZCS();
	m_a ^= m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0010 0100   aaaa aaaa
 *  x x x x AI   aa
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_ai()
{
	ROMC_03(cL);
	CLR_OZCS();
	m_a = do_add(m_a,m_dbus);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0010 0101   aaaa aaaa
 *  x x x x CI   aa
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_ci()
{
	ROMC_03(cL);
	CLR_OZCS();
	SET_SZ(do_add(~m_a,m_dbus,1));
}

/***************************************************
 *  O Z C S 0010 0110   aaaa aaaa
 *  0 x 0 x IN   aa
 ***************************************************/
void F8::f8_in()
{
	ROMC_03(cL);
	CLR_OZCS();
	ROMC_1B();
	m_a = m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 0010 0111   aaaa aaaa
 *  - - - - OUT  aa
 ***************************************************/
void F8::f8_out()
{
	ROMC_03(cL);
	m_dbus = m_a;
	ROMC_1A();
}

/***************************************************
 *  O Z C S 0010 1000   iiii iiii   jjjj jjjj
 *  - - - - PI   iijj
 ***************************************************/
void F8::f8_pi()
{
	ROMC_03(cL);
	m_a = m_dbus;
	ROMC_0D();
	ROMC_0C();
	m_dbus = m_a;
	ROMC_14();
}

/***************************************************
 *  O Z C S 0010 1001   iiii iiii   jjjj jjjj
 *  - - - - JMP  iijj
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_jmp()
{
	ROMC_03(cL);
	m_a = m_dbus;
	ROMC_0C();
	m_dbus = m_a;
	ROMC_14();
}

/***************************************************
 *  O Z C S 0010 1010   iiii iiii   jjjj jjjj
 *  - - - - DCI  iijj
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_dci()
{
	ROMC_11();
	ROMC_03(cS);
	ROMC_0E();
	ROMC_03(cS);
}

/***************************************************
 *  O Z C S 0010 1011
 *  - - - - NOP
 ***************************************************/
void F8::f8_nop()
{
}

/***************************************************
 *  O Z C S 0010 1100
 *  - - - - XDC
 ***************************************************/
void F8::f8_xdc()
{
	ROMC_1D();
}

/***************************************************
 *  O Z C S 0011 rrrr
 *  x x x x DS   r
 ***************************************************/
void F8::f8_ds_r(int r)
{
	CLR_OZCS();
	int d = do_add(read_reg(r), 0xff);
	write_reg(r, d);
	SET_SZ(d);
}

/***************************************************
 *  O Z C S 0011 1100
 *  x x x x DS   ISAR
 ***************************************************/
void F8::f8_ds_isar()
{
	CLR_OZCS();
	int d = do_add(read_reg(m_is), 0xff);
	write_reg(m_is, d);
	SET_SZ(d);
}

/***************************************************
 *  O Z C S 0011 1101
 *  x x x x DS   ISAR++
 ***************************************************/
void F8::f8_ds_isar_i()
{
	CLR_OZCS();
	int d = do_add(read_reg(m_is), 0xff);
	write_reg(m_is, d);
	SET_SZ(d);
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 0011 1110
 *  x x x x DS  ISAR--
 ***************************************************/
void F8::f8_ds_isar_d()
{
	CLR_OZCS();
	int d = do_add(read_reg(m_is), 0xff);
	write_reg(m_is, d);
	SET_SZ(d);
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}

/***************************************************
 *  O Z C S 0100 rrrr
 *  - - - - LR  A,r
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_lr_a_r(int r)
{
	m_a = read_reg(r);
}

/***************************************************
 *  O Z C S 0100 1100
 *  - - - - LR  A,ISAR
 ***************************************************/
void F8::f8_lr_a_isar()
{
	m_a = read_reg(m_is);
}

/***************************************************
 *  O Z C S 0100 1101
 *  - - - - LR  A,ISAR++
 ***************************************************/
void F8::f8_lr_a_isar_i()
{
	m_a = read_reg(m_is);
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 0100 1110
 *  - - - - LR  A,ISAR--
 ***************************************************/
void F8::f8_lr_a_isar_d()
{
	m_a = read_reg(m_is);
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}

/***************************************************
 *  O Z C S 0101 rrrr
 *  - - - - LR  r,A
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_lr_r_a(int r)
{
	write_reg(r, m_a);
}

/***************************************************
 *  O Z C S 0101 1100
 *  - - - - LR  ISAR,A
 ***************************************************/
void F8::f8_lr_isar_a()
{
	write_reg(m_is, m_a);
}

/***************************************************
 *  O Z C S 0101 1101
 *  - - - - LR  ISAR++,A
 ***************************************************/
void F8::f8_lr_isar_i_a()
{
	write_reg(m_is, m_a);
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 0101 1110
 *  - - - - LR  ISAR--,A
 ***************************************************/
void F8::f8_lr_isar_d_a()
{
	write_reg(m_is, m_a);
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}

/***************************************************
 *  O Z C S 0110 0eee
 *  - - - - LISU e
 ***************************************************/
void F8::f8_lisu(int e)
{
	m_is = (m_is & 0x07) | e;
}

/***************************************************
 *  O Z C S 0110 1eee
 *  - - - - LISL e
 ***************************************************/
void F8::f8_lisl(int e)
{
	m_is = (m_is & 0x38) | e;
}

/***************************************************
 *  O Z C S 0111 iiii
 *  - - - - LIS  i
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_lis(int i)
{
	m_a = i;
}

/***************************************************
 *  O Z C S 1000 0eee   aaaa aaaa
 *          BT   e,aa
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_bt(int e)
{
	ROMC_1C(cS);
	if (m_w & e)
		ROMC_01(); // take the relative branch
	else
		ROMC_03(cS); // just read the argument on the data bus
}

/***************************************************
 *  O Z C S 1000 1000
 *  x x x x AM
 ***************************************************/
void F8::f8_am()
{
	ROMC_02();
	CLR_OZCS();
	m_a = do_add(m_a, m_dbus);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1000 1001
 *  x x x x AMD
 ***************************************************/
void F8::f8_amd()
{
	ROMC_02();
	m_a = do_add_decimal(m_a, m_dbus);
}

/***************************************************
 *  O Z C S 1000 1010
 *  0 x 0 x NM
 ***************************************************/
void F8::f8_nm()
{
	ROMC_02();
	CLR_OZCS();
	m_a &= m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1000 1011
 *  0 x 0 x OM
 ***************************************************/
void F8::f8_om()
{
	ROMC_02();
	CLR_OZCS();
	m_a |= m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1000 1100
 *  0 x 0 x XM
 ***************************************************/
void F8::f8_xm()
{
	ROMC_02();
	CLR_OZCS();
	m_a ^= m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1000 1101
 *  x x x x CM
 ***************************************************/
void F8::f8_cm()
{
	ROMC_02();
	CLR_OZCS();
	SET_SZ(do_add(~m_a,m_dbus,1));
}

/***************************************************
 *  O Z C S 1000 1110
 *  - - - - ADC
 ***************************************************/
void F8::f8_adc()
{
	m_dbus = m_a;
	ROMC_0A(); // add data bus value to DC0
}

/***************************************************
 *  O Z C S 1000 1111
 *  - - - - BR7
 ***************************************************/
void F8::f8_br7()
{
	if ((m_is & 7) == 7)
		ROMC_03(cS); // just read the argument on the data bus
	else
		ROMC_01(); // take the relative branch
}

/***************************************************
 *  O Z C S 1001 tttt   aaaa aaaa
 *  - - - - BF   t,aa
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_bf(int t)
{
	ROMC_1C(cS);
	if (m_w & t)
		ROMC_03(cS); // just read the argument on the data bus
	else
		ROMC_01(); // take the relative branch
}

/***************************************************
 *  O Z C S 1010 000n
 *  0 x 0 x INS  n              (n = 0-1)
 ***************************************************/
void F8::f8_ins_0(int n)
{
	ROMC_1C(cS);
	CLR_OZCS();
	m_a = read_io(n);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1010 nnnn
 *  0 x 0 x INS  n              (n = 4-F)
 ***************************************************/
void F8::f8_ins_1(int n)
{
	ROMC_1C(cL);
	m_io = n;
	ROMC_1B();
	CLR_OZCS();
	m_a = m_dbus;
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1011 000n
 *  - - - - OUTS n              (n = 0-1)
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_outs_0(int n)
{
	ROMC_1C(cS);
	write_io(n, m_a);
}

/***************************************************
 *  O Z C S 1011 nnnn
 *  - - - - OUTS n              (n = 4-F)
 ***************************************************/
void F8::f8_outs_1(int n)
{
	ROMC_1C(cL);
	m_io = n;
	m_dbus = m_a;
	ROMC_1A();
}

/***************************************************
 *  O Z C S 1100 rrrr
 *  x x x x AS   r
 ***************************************************/
__attribute__((always_inline)) inline void F8::f8_as(int r)
{
	CLR_OZCS();
	m_a = do_add(m_a, read_reg(r));
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1100 1100
 *  x x x x AS   ISAR
 ***************************************************/
void F8::f8_as_isar()
{
	CLR_OZCS();
	m_a = do_add(m_a, read_reg(m_is));
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1100 1101
 *  x x x x AS   ISAR++
 ***************************************************/
void F8::f8_as_isar_i()
{
	CLR_OZCS();
	m_a = do_add(m_a, read_reg(m_is));
	SET_SZ(m_a);
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 1100 1110
 *  x x x x AS   ISAR--
 ***************************************************/
void F8::f8_as_isar_d()
{
	CLR_OZCS();
	m_a = do_add(m_a, read_reg(m_is));
	SET_SZ(m_a);
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}

/***************************************************
 *  O Z C S 1101 rrrr
 *  x x x x ASD  r
 ***************************************************/
void F8::f8_asd(int r)
{
	ROMC_1C(cS);
	m_a = do_add_decimal(m_a, read_reg(r));
}

/***************************************************
 *  O Z C S 1101 1100
 *  x x x x ASD  ISAR
 ***************************************************/
void F8::f8_asd_isar()
{
	ROMC_1C(cS);
	m_a = do_add_decimal(m_a, read_reg(m_is));
}

/***************************************************
 *  O Z C S 1101 1101
 *  x x x x ASD  ISAR++
 ***************************************************/
void F8::f8_asd_isar_i()
{
	ROMC_1C(cS);
	m_a = do_add_decimal(m_a, read_reg(m_is));
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 1101 1110
 *  x x x x ASD  ISAR--
 ***************************************************/
void F8::f8_asd_isar_d()
{
	ROMC_1C(cS);
	m_a = do_add_decimal(m_a, read_reg(m_is));
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}

/***************************************************
 *  O Z C S 1110 rrrr
 *  0 x 0 x XS   r
 ***************************************************/
void F8::f8_xs(int r)
{
	CLR_OZCS();
	m_a ^= read_reg(r);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1110 1100
 *  0 x 0 x XS   ISAR
 ***************************************************/
void F8::f8_xs_isar()
{
	CLR_OZCS();
	m_a ^= read_reg(m_is);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1110 1101
 *  0 x 0 x XS   ISAR++
 ***************************************************/
void F8::f8_xs_isar_i()
{
	CLR_OZCS();
	m_a ^= read_reg(m_is);
	SET_SZ(m_a);
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 1110 1110
 *  0 x 0 x XS   ISAR--
 ***************************************************/
void F8::f8_xs_isar_d()
{
	CLR_OZCS();
	m_a ^= read_reg(m_is);
	SET_SZ(m_a);
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}

/***************************************************
 *  O Z C S 1111 rrrr
 *  0 x 0 x NS   r
 ***************************************************/
void F8::f8_ns(int r)
{
	CLR_OZCS();
	m_a &= read_reg(r);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1111 1100
 *  0 x 0 x NS   ISAR
 ***************************************************/
void F8::f8_ns_isar()
{
	CLR_OZCS();
	m_a &= read_reg(m_is);
	SET_SZ(m_a);
}

/***************************************************
 *  O Z C S 1111 1101
 *  0 x 0 x NS   ISAR++
 ***************************************************/
void F8::f8_ns_isar_i()
{
	CLR_OZCS();
	m_a &= read_reg(m_is);
	SET_SZ(m_a);
	m_is = (m_is & 0x38) | ((m_is + 1) & 0x07);
}

/***************************************************
 *  O Z C S 1111 1110
 *  0 x 0 x NS   ISAR--
 ***************************************************/
void F8::f8_ns_isar_d()
{
	CLR_OZCS();
	m_a &= read_reg(m_is);
	SET_SZ(m_a);
	m_is = (m_is & 0x38) | ((m_is - 1) & 0x07);
}


/***************************************************
 *  Execute cycles
 ***************************************************/

#ifdef DELTA_PROFILE
uint64_t delta_pc_hist[4096] = {};
uint64_t delta_op_hist[256] = {};
uint64_t delta_steps=0;
#endif
void F8::execute_run()
{
	do
	{
        // Original ROM $0702-$0708: LIS 7 / NS 11 / AS 11 / SR 1 / DCI #EC40.
        if ((m_pc0 & 0x2fff) == 0x0703 && m_dbus == 0x77 &&
            rom[0x0702] == 0x77 && rom[0x0703] == 0xfb &&
            rom[0x0704] == 0xcb && rom[0x0705] == 0x12 &&
            rom[0x0706] == 0x2a && rom[0x0707] == 0xec &&
            rom[0x0708] == 0x40 && rom[0x0709] == 0x8e &&
            !(m_w & I && m_irq_request) && m_icount >= 40 &&
            (timer_next == UINT64_MAX || timer_next > cycles+40)) {
            m_a = 7;
            CLR_OZCS(); m_a &= regs[11]; SET_SZ(m_a);
            CLR_OZCS(); m_a = do_add(m_a,regs[11]); SET_SZ(m_a);
            m_a >>= 1; CLR_OZCS(); SET_SZ(m_a);
            m_dc0 = 0xec40;
            m_io = 0x40;
            m_dbus = 0x8e;
            m_pc0 += 7;

            m_icount -= 40;
            cycles += 40;

            step_icount = m_icount;
            continue;
        }
        // Superinstruction for the immutable original-ROM sequence $06FB-$06FF.
        // Execute LR K,P / AS 11 / LR 11,A / NI #$88 as one native block.
        // No port accesses; precise timer/IRQ and partial-run fallback.
        if ((m_pc0 & 0x2fff) == 0x06fc && m_dbus == 0x08 &&
            rom[0x06fb] == 0x08 && rom[0x06fc] == 0xcb &&
            rom[0x06fd] == 0x5b && rom[0x06fe] == 0x21 &&
            rom[0x06ff] == 0x88 && rom[0x0700] == 0x94 &&
            !(m_w & I && m_irq_request) && m_icount >= 34 &&
            (timer_next == UINT64_MAX || timer_next > cycles + 34)) {
            regs[12] = u8(m_pc1 >> 8);
            regs[13] = u8(m_pc1);
            CLR_OZCS();
            m_a = do_add(m_a, regs[11]);
            SET_SZ(m_a);
            regs[11] = m_a;
            m_io = 0x88;
            CLR_OZCS();
            m_a &= 0x88;
            SET_SZ(m_a);
            m_pc0 += 5;
            m_dbus = 0x94;

            m_icount -= 34;
            cycles += 34;

            step_icount = m_icount;
            continue;
        }
        // Original ROM hot loop at $0492: AS 5 / DS 4 / BF 4,$FD.
        // Batch only the non-final iterations, and stop BEFORE a timer edge,
        // an IRQ service point, or the caller's requested cycle boundary.
        // Each taken iteration costs exactly 24 F8 cycles (4+6+10+4).
        if (((m_pc0 & 0x2fff) == 0x0493) && m_dbus == 0xc5 &&
            read_mem(0x0492) == 0xc5 && read_mem(0x0493) == 0x34 &&
            read_mem(0x0494) == 0x94 && read_mem(0x0495) == 0xfd &&
            !(m_w & I && m_irq_request) && m_icount > 24) {
            const unsigned count = regs[4] ? regs[4] : 256;
            uint64_t n = std::min<uint64_t>(count - 1, (m_icount - 1) / 24);
            if (timer_next != UINT64_MAX) {
                if (timer_next <= cycles) n = 0;
                else n = std::min<uint64_t>(n, (timer_next - cycles - 1) / 24);
            }
            if (n) {
                const u8 last_before = u8(regs[4] - (n - 1));
                m_a = u8(m_a + n * regs[5]);
                regs[4] = u8(regs[4] - n);
                CLR_OZCS();
                const u8 v = do_add(last_before, 0xff);
                SET_SZ(v);

                cycles += 24 * n;

                m_icount -= 24 * n;
                step_icount = m_icount;
                continue;
            }
        }
		step_icount = m_icount;
		u8 op = m_dbus;
#ifdef DELTA_PROFILE
        if ((++delta_steps & 1023) == 0) {
            ++delta_pc_hist[(m_pc0-1)&4095];
            ++delta_op_hist[op];
        }
#endif




		switch (op)
		{
			case 0x00: f8_lr_a_ku(); break;
			case 0x01: f8_lr_a_kl(); break;
			case 0x02: f8_lr_a_qu(); break;
			case 0x03: f8_lr_a_ql(); break;
			case 0x04: f8_lr_ku_a(); break;
			case 0x05: f8_lr_kl_a(); break;
			case 0x06: f8_lr_qu_a(); break;
			case 0x07: f8_lr_ql_a(); break;
			case 0x08: f8_lr_k_p(); break;
			case 0x09: f8_lr_p_k(); break;
			case 0x0a: f8_lr_a_is(); break;
			case 0x0b: f8_lr_is_a(); break;
			case 0x0c: f8_pk(); break;
			case 0x0d: f8_lr_p0_q(); break;
			case 0x0e: f8_lr_q_dc(); break;
			case 0x0f: f8_lr_dc_q(); break;

			case 0x10: f8_lr_dc_h(); break;
			case 0x11: f8_lr_h_dc(); break;
			case 0x12: f8_sr_1(); break;
			case 0x13: f8_sl_1(); break;
			case 0x14: f8_sr_4(); break;
			case 0x15: f8_sl_4(); break;
			case 0x16: f8_lm(); break;
			case 0x17: f8_st(); break;
			case 0x18: f8_com(); break;
			case 0x19: f8_lnk(); break;
			case 0x1a: f8_di(); break;
			case 0x1b: f8_ei(); break;
			case 0x1c: f8_pop(); break;
			case 0x1d: f8_lr_w_j(); break;
			case 0x1e: f8_lr_j_w(); break;
			case 0x1f: f8_inc(); break;

			case 0x20: f8_li(); break;
			case 0x21: f8_ni(); break;
			case 0x22: f8_oi(); break;
			case 0x23: f8_xi(); break;
			case 0x24: f8_ai(); break;
			case 0x25: f8_ci(); break;
			case 0x26: f8_in(); break;
			case 0x27: f8_out(); break;
			case 0x28: f8_pi(); break;
			case 0x29: f8_jmp(); break;
			case 0x2a: f8_dci(); break;
			case 0x2b: f8_nop(); break;
			case 0x2c: f8_xdc(); break;
			case 0x2d: illegal(); break;
			case 0x2e: illegal(); break;
			case 0x2f: illegal(); break;

			case 0x30: f8_ds_r(0); break;
			case 0x31: f8_ds_r(1); break;
			case 0x32: f8_ds_r(2); break;
			case 0x33: f8_ds_r(3); break;
			case 0x34: f8_ds_r(4); break;
			case 0x35: f8_ds_r(5); break;
			case 0x36: f8_ds_r(6); break;
			case 0x37: f8_ds_r(7); break;
			case 0x38: f8_ds_r(8); break;
			case 0x39: f8_ds_r(9); break;
			case 0x3a: f8_ds_r(10); break;
			case 0x3b: f8_ds_r(11); break;
			case 0x3c: f8_ds_isar(); break;
			case 0x3d: f8_ds_isar_i(); break;
			case 0x3e: f8_ds_isar_d(); break;
			case 0x3f: illegal(); break;

			case 0x40: f8_lr_a_r(0); break;
			case 0x41: f8_lr_a_r(1); break;
			case 0x42: f8_lr_a_r(2); break;
			case 0x43: f8_lr_a_r(3); break;
			case 0x44: f8_lr_a_r(4); break;
			case 0x45: f8_lr_a_r(5); break;
			case 0x46: f8_lr_a_r(6); break;
			case 0x47: f8_lr_a_r(7); break;
			case 0x48: f8_lr_a_r(8); break;
			case 0x49: f8_lr_a_r(9); break;
			case 0x4a: f8_lr_a_r(10); break;
			case 0x4b: f8_lr_a_r(11); break;
			case 0x4c: f8_lr_a_isar(); break;
			case 0x4d: f8_lr_a_isar_i(); break;
			case 0x4e: f8_lr_a_isar_d(); break;
			case 0x4f: illegal(); break;

			case 0x50: f8_lr_r_a(0); break;
			case 0x51: f8_lr_r_a(1); break;
			case 0x52: f8_lr_r_a(2); break;
			case 0x53: f8_lr_r_a(3); break;
			case 0x54: f8_lr_r_a(4); break;
			case 0x55: f8_lr_r_a(5); break;
			case 0x56: f8_lr_r_a(6); break;
			case 0x57: f8_lr_r_a(7); break;
			case 0x58: f8_lr_r_a(8); break;
			case 0x59: f8_lr_r_a(9); break;
			case 0x5a: f8_lr_r_a(10); break;
			case 0x5b: f8_lr_r_a(11); break;
			case 0x5c: f8_lr_isar_a(); break;
			case 0x5d: f8_lr_isar_i_a(); break;
			case 0x5e: f8_lr_isar_d_a(); break;
			case 0x5f: illegal(); break;

			case 0x60: f8_lisu(0x00); break;
			case 0x61: f8_lisu(0x08); break;
			case 0x62: f8_lisu(0x10); break;
			case 0x63: f8_lisu(0x18); break;
			case 0x64: f8_lisu(0x20); break;
			case 0x65: f8_lisu(0x28); break;
			case 0x66: f8_lisu(0x30); break;
			case 0x67: f8_lisu(0x38); break;
			case 0x68: f8_lisl(0x00); break;
			case 0x69: f8_lisl(0x01); break;
			case 0x6a: f8_lisl(0x02); break;
			case 0x6b: f8_lisl(0x03); break;
			case 0x6c: f8_lisl(0x04); break;
			case 0x6d: f8_lisl(0x05); break;
			case 0x6e: f8_lisl(0x06); break;
			case 0x6f: f8_lisl(0x07); break;

			case 0x70: f8_lis(0x0); break;
			case 0x71: f8_lis(0x1); break;
			case 0x72: f8_lis(0x2); break;
			case 0x73: f8_lis(0x3); break;
			case 0x74: f8_lis(0x4); break;
			case 0x75: f8_lis(0x5); break;
			case 0x76: f8_lis(0x6); break;
			case 0x77: f8_lis(0x7); break;
			case 0x78: f8_lis(0x8); break;
			case 0x79: f8_lis(0x9); break;
			case 0x7a: f8_lis(0xa); break;
			case 0x7b: f8_lis(0xb); break;
			case 0x7c: f8_lis(0xc); break;
			case 0x7d: f8_lis(0xd); break;
			case 0x7e: f8_lis(0xe); break;
			case 0x7f: f8_lis(0xf); break;

			case 0x80: f8_bt(0); break;
			case 0x81: f8_bt(1); break;
			case 0x82: f8_bt(2); break;
			case 0x83: f8_bt(3); break;
			case 0x84: f8_bt(4); break;
			case 0x85: f8_bt(5); break;
			case 0x86: f8_bt(6); break;
			case 0x87: f8_bt(7); break;
			case 0x88: f8_am(); break;
			case 0x89: f8_amd(); break;
			case 0x8a: f8_nm(); break;
			case 0x8b: f8_om(); break;
			case 0x8c: f8_xm(); break;
			case 0x8d: f8_cm(); break;
			case 0x8e: f8_adc(); break;
			case 0x8f: f8_br7(); break;

			case 0x90: f8_bf(0x0); break;
			case 0x91: f8_bf(0x1); break;
			case 0x92: f8_bf(0x2); break;
			case 0x93: f8_bf(0x3); break;
			case 0x94: f8_bf(0x4); break;
			case 0x95: f8_bf(0x5); break;
			case 0x96: f8_bf(0x6); break;
			case 0x97: f8_bf(0x7); break;
			case 0x98: f8_bf(0x8); break;
			case 0x99: f8_bf(0x9); break;
			case 0x9a: f8_bf(0xa); break;
			case 0x9b: f8_bf(0xb); break;
			case 0x9c: f8_bf(0xc); break;
			case 0x9d: f8_bf(0xd); break;
			case 0x9e: f8_bf(0xe); break;
			case 0x9f: f8_bf(0xf); break;

			case 0xa0: f8_ins_0(0x0); break;
			case 0xa1: f8_ins_0(0x1); break;
			case 0xa2: illegal(); break;
			case 0xa3: illegal(); break;
			case 0xa4: f8_ins_1(0x4); break;
			case 0xa5: f8_ins_1(0x5); break;
			case 0xa6: f8_ins_1(0x6); break;
			case 0xa7: f8_ins_1(0x7); break;
			case 0xa8: f8_ins_1(0x8); break;
			case 0xa9: f8_ins_1(0x9); break;
			case 0xaa: f8_ins_1(0xa); break;
			case 0xab: f8_ins_1(0xb); break;
			case 0xac: f8_ins_1(0xc); break;
			case 0xad: f8_ins_1(0xd); break;
			case 0xae: f8_ins_1(0xe); break;
			case 0xaf: f8_ins_1(0xf); break;

			case 0xb0: f8_outs_0(0x0); break;
			case 0xb1: f8_outs_0(0x1); break;
			case 0xb2: illegal(); break;
			case 0xb3: illegal(); break;
			case 0xb4: f8_outs_1(0x4); break;
			case 0xb5: f8_outs_1(0x5); break;
			case 0xb6: f8_outs_1(0x6); break;
			case 0xb7: f8_outs_1(0x7); break;
			case 0xb8: f8_outs_1(0x8); break;
			case 0xb9: f8_outs_1(0x9); break;
			case 0xba: f8_outs_1(0xa); break;
			case 0xbb: f8_outs_1(0xb); break;
			case 0xbc: f8_outs_1(0xc); break;
			case 0xbd: f8_outs_1(0xd); break;
			case 0xbe: f8_outs_1(0xe); break;
			case 0xbf: f8_outs_1(0xf); break;

			case 0xc0: f8_as(0x0); break;
			case 0xc1: f8_as(0x1); break;
			case 0xc2: f8_as(0x2); break;
			case 0xc3: f8_as(0x3); break;
			case 0xc4: f8_as(0x4); break;
			case 0xc5: f8_as(0x5); break;
			case 0xc6: f8_as(0x6); break;
			case 0xc7: f8_as(0x7); break;
			case 0xc8: f8_as(0x8); break;
			case 0xc9: f8_as(0x9); break;
			case 0xca: f8_as(0xa); break;
			case 0xcb: f8_as(0xb); break;
			case 0xcc: f8_as_isar(); break;
			case 0xcd: f8_as_isar_i(); break;
			case 0xce: f8_as_isar_d(); break;
			case 0xcf: illegal(); break;

			case 0xd0: f8_asd(0x0); break;
			case 0xd1: f8_asd(0x1); break;
			case 0xd2: f8_asd(0x2); break;
			case 0xd3: f8_asd(0x3); break;
			case 0xd4: f8_asd(0x4); break;
			case 0xd5: f8_asd(0x5); break;
			case 0xd6: f8_asd(0x6); break;
			case 0xd7: f8_asd(0x7); break;
			case 0xd8: f8_asd(0x8); break;
			case 0xd9: f8_asd(0x9); break;
			case 0xda: f8_asd(0xa); break;
			case 0xdb: f8_asd(0xb); break;
			case 0xdc: f8_asd_isar(); break;
			case 0xdd: f8_asd_isar_i(); break;
			case 0xde: f8_asd_isar_d(); break;
			case 0xdf: illegal(); break;

			case 0xe0: f8_xs(0x0); break;
			case 0xe1: f8_xs(0x1); break;
			case 0xe2: f8_xs(0x2); break;
			case 0xe3: f8_xs(0x3); break;
			case 0xe4: f8_xs(0x4); break;
			case 0xe5: f8_xs(0x5); break;
			case 0xe6: f8_xs(0x6); break;
			case 0xe7: f8_xs(0x7); break;
			case 0xe8: f8_xs(0x8); break;
			case 0xe9: f8_xs(0x9); break;
			case 0xea: f8_xs(0xa); break;
			case 0xeb: f8_xs(0xb); break;
			case 0xec: f8_xs_isar(); break;
			case 0xed: f8_xs_isar_i(); break;
			case 0xee: f8_xs_isar_d(); break;
			case 0xef: illegal(); break;

			case 0xf0: f8_ns(0x0); break;
			case 0xf1: f8_ns(0x1); break;
			case 0xf2: f8_ns(0x2); break;
			case 0xf3: f8_ns(0x3); break;
			case 0xf4: f8_ns(0x4); break;
			case 0xf5: f8_ns(0x5); break;
			case 0xf6: f8_ns(0x6); break;
			case 0xf7: f8_ns(0x7); break;
			case 0xf8: f8_ns(0x8); break;
			case 0xf9: f8_ns(0x9); break;
			case 0xfa: f8_ns(0xa); break;
			case 0xfb: f8_ns(0xb); break;
			case 0xfc: f8_ns_isar(); break;
			case 0xfd: f8_ns_isar_i(); break;
			case 0xfe: f8_ns_isar_d(); break;
			case 0xff: illegal(); break;
		}
		switch (op)
		{
			case 0x0c: case 0x1b: case 0x1c: case 0x1d:
			case 0x27: case 0x28: case 0x29:
			case 0xb4: case 0xb5: case 0xb6: case 0xb7:
			case 0xb8: case 0xb9: case 0xba: case 0xbb:
			case 0xbc: case 0xbd: case 0xbe: case 0xbf:
				// don't handle irq after privileged instruction
				ROMC_00(cS);
				break;

			default:
				// 'freeze cycle' for handling interrupts
				if (m_w&I && m_irq_request)
				{
					ROMC_10();
					ROMC_1C(cL);
					ROMC_0F();
					ROMC_13();
				}

				// fetch next instruction (DS is long cycle)
				if ((op >= 0x30) && (op <= 0x3f))
					ROMC_00(cL);
				else
					ROMC_00(cS);

				break;
		}
		advance(step_icount - m_icount);
	} while( m_icount > 0 );
}
