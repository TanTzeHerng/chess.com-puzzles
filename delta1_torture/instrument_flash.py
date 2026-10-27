from pathlib import Path
p=Path(__file__).with_name('f8_rom_patched.h')
s=p.read_text()
old=' u8 mux=0,seg=0;bool rc=false;'
new=' u8 mux=0,seg=0;bool rc=false;\n char flash_target[5]{};bool flash_armed=false,flash_seen=false;uint64_t flash_cycle=0;\n'
assert old in s;s=s.replace(old,new)
old='   display_cycle=t;\n }'
new='''   display_cycle=t;
   if(flash_armed && !flash_seen && t>=flash_cycle && display()==std::string(flash_target,4)){
     flash_seen=true;flash_cycle=t;
   }
 }'''
assert old in s;s=s.replace(old,new,1)
p.write_text(s)
f=Path(__file__).with_name('torture_engine.cpp')
s=f.read_text()
old='void advance_search(double emulated_seconds){'
new=r'''void watch_move(const std::string& target){
 if(target.size()!=4)throw std::runtime_error("watch requires 4-char move");
 for(int k=0;k<4;k++)m.flash_target[k]=target[k];
 m.flash_target[4]=0;
 m.flash_armed=true;m.flash_seen=false;m.flash_cycle=m.cycles+100000;
 std::cout<<"watching "<<target<<" board_hex="<<boardhex()<<"\n"<<std::flush;
}
void advance_search(double emulated_seconds){'''
assert old in s;s=s.replace(old,new)
s=s.replace('uint64_t chunk=std::min<uint64_t>(amount,20000000);m.run(chunk);amount-=chunk;','uint64_t chunk=std::min<uint64_t>(amount,200000);m.run(chunk);amount-=chunk;\n   if(m.flash_seen)break;')
s=s.replace('<<" board_hex="<<boardhex()<<" illegal_opcodes="<<m.illegal_count','<<" board_hex="<<boardhex()<<" illegal_opcodes="<<m.illegal_count\n  <<" flash_seen="<<(m.flash_seen?1:0)<<" flash_cycle="<<m.flash_cycle')
s=s.replace('else if(line.rfind("advance ",0)==0)advance_search(std::stod(line.substr(8)));','else if(line.rfind("watch ",0)==0)watch_move(line.substr(6));\n    else if(line.rfind("advance ",0)==0)advance_search(std::stod(line.substr(8)));')
s=s.replace('m.move(u);candidate_ready=false;search_start=m.cycles;','m.move(u);candidate_ready=false;m.flash_armed=false;m.flash_seen=false;search_start=m.cycles;')
s=s.replace('m.level("999999");\n std::cout<<"adopted', 'm.level("999999");m.flash_armed=false;m.flash_seen=false;\n std::cout<<"adopted')
f.write_text(s)
print("INSTALLED flash monitor at actual four-digit display updates; time is preserved")
