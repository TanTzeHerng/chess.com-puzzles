from pathlib import Path
p=Path(__file__).with_name('torture_engine.cpp')
s=p.read_text()
start=s.index('void go(){')
s=s[:start]+r'''
void advance_search(double emulated_seconds){
 if(!std::isfinite(emulated_seconds)||emulated_seconds<=0||emulated_seconds>7200)
   throw std::runtime_error("Invalid slice seconds");
 uint64_t amount=uint64_t(std::llround(emulated_seconds*2000000.));
 auto begin=m.cycles;
 while(amount){uint64_t chunk=std::min<uint64_t>(amount,20000000);m.run(chunk);amount-=chunk;}
 std::cout<<"advanced seconds="<<double(m.cycles-begin)/2000000
  <<" current_clock_bcd="<<std::hex<<int(m.regs[17])<<":"
  <<int(m.regs[19])<<":"<<int(m.regs[21])<<std::dec
  <<" board_hex="<<boardhex()<<" illegal_opcodes="<<m.illegal_count<<"\n"<<std::flush;
}
void probe(){
 candidate=m;candidate_ready=false;
 auto before=boardhex();
 auto iscoord=[](const std::string&s)->bool{
   return s.size()==4 && s[0]>='a'&&s[0]<='h' &&s[1]>='1'&&s[1]<='8'
   &&s[2]>='a'&&s[2]<='h' &&s[3]>='1'&&s[3]<='8';
 };
 // If the ROM has already returned a move without prompting, reuse it.
 if(!((candidate.regs[6]&8)&&iscoord(candidate.display()))){
   candidate.press(0,2,.12); // TIME SET - manual: end active search
   candidate.press(3,8,.12); // CE: release latest proposed move
 }
 std::string prev,answer;int stable=0;
 for(int k=0;k<15000;k++){
  candidate.run(20000);std::string s=candidate.display();
  if((candidate.regs[6]&8)&&iscoord(s)){
    stable=(s==prev?stable+1:0);prev=s;
    if(stable>=4){answer=s;candidate_ready=true;break;}
  }else stable=0;
 }
 // Reconsidering an illegal move never advances the canonical search state.
 if(before!=boardhex())throw std::runtime_error("probe mutated active search");
 std::cout<<"probe_move "<<(answer.empty()?"0000":answer)
  <<" original_board_hex="<<before<<" candidate_board_hex="<<
  [&](){std::ostringstream out;out<<std::hex<<std::setfill('0');for(int i=64;i<128;i++)
      out<<std::setw(2)<<int(candidate.ram[i]);return out.str();}()
  <<" rom_errors="<<candidate.illegal_count
  <<" search_cycles="<<m.cycles<<" probe_cycles="<<candidate.cycles
  <<"\n"<<std::flush;
}
void adopt(){
 if(!candidate_ready)throw std::runtime_error("No verified candidate to adopt");
 if(candidate.rom!=embedded_rom)throw std::runtime_error("Wrong experimental ROM");
 m=candidate;candidate_ready=false;
 std::cout<<"adopted board_hex="<<boardhex()<<"\n"<<std::flush;
}
int main(int argc,char**argv){
 try{
  if(m.rom[0xd2c]!=0x2b)throw std::runtime_error("Missing experimental extended ROM");
  std::string line;
  while(std::getline(std::cin,line)){
   try{
    if(line.rfind("setup ",0)==0)setup(line.substr(6));
    else if(line.rfind("play ",0)==0){
     std::string u=line.substr(5);
     if(u.size()!=4)throw std::runtime_error("Four-character moves only");
     m.move(u);candidate_ready=false;search_start=m.cycles;
     std::cout<<"played "<<u<<" board_hex="<<boardhex()<<"\n"<<std::flush;
    }
    else if(line.rfind("advance ",0)==0)advance_search(std::stod(line.substr(8)));
    else if(line=="probe")probe();
    else if(line=="adopt")adopt();
    else if(line.rfind("load ",0)==0){
      load_checkpoint(line.substr(5));candidate_ready=false;
      std::cout<<"loaded board_hex="<<boardhex()<<"\n"<<std::flush;
    }
    else if(line.rfind("save ",0)==0){
      checkpoint_path=line.substr(5);checkpoint();
      std::cout<<"saved board_hex="<<boardhex()<<"\n"<<std::flush;
    }
    else if(line=="dump"){
      std::cout<<"dump board_hex="<<boardhex()<<" flags="<<int(m.regs[6])
       <<" rom_clock_hms_bcd="<<std::hex<<int(m.regs[17])<<":"
       <<int(m.regs[19])<<":"<<int(m.regs[21])<<std::dec<<"\n"<<std::flush;
    }
    else if(line=="quit")break;
    else std::cout<<"error unknown_command\n"<<std::flush;
   }catch(const std::exception&e){std::cout<<"error "<<e.what()<<"\n"<<std::flush;}
  }
  return 0;
 }catch(const std::exception&e){std::cerr<<"fatal "<<e.what()<<"\n";return 2;}
}
'''
s=s.replace('D1PZCP01','D1TRCP01')
s=s.replace('#include <type_traits>','#include <type_traits>\n#include <cmath>')
p.write_text(s)
print('WROTE',p,len(s))
