// Separate puzzle adapter. Chess moves and evaluations come only from the unchanged ROM.
#include "f8_rom_patched.h"
#include <sstream>
#include <thread>
#include <filesystem>
#include <type_traits>
#include <cmath>
F8 m("@embedded");
F8 candidate("@embedded");
bool candidate_ready=false;
uint64_t search_start=0;
std::string checkpoint_path;
void checkpoint(){
 if(checkpoint_path.empty())return;
 static_assert(std::is_trivially_copyable<F8>::value,"Checkpoint requires pointer-free emulated state");
 std::ofstream f(checkpoint_path+".tmp",std::ios::binary|std::ios::trunc);
 uint64_t size=sizeof(F8);f.write("D1TRCP01",8);f.write((char*)&size,8);f.write((char*)&m,sizeof(m));f.close();
 if(!f)throw std::runtime_error("Checkpoint write failed");std::filesystem::rename(checkpoint_path+".tmp",checkpoint_path);
}
void load_checkpoint(const std::string&p){
 std::ifstream f(p,std::ios::binary);char magic[8];uint64_t size=0;f.read(magic,8);f.read((char*)&size,8);
 if(!f||std::string(magic,8)!="D1TRCP01"||size!=sizeof(F8))throw std::runtime_error("Incompatible checkpoint");
 F8 loaded("@embedded");f.read((char*)&loaded,sizeof(loaded));if(!f||loaded.rom!=embedded_rom)throw std::runtime_error("Invalid checkpoint ROM/state");m=loaded;
 std::cout<<"loaded checkpoint cycles="<<m.cycles<<"\n"<<std::flush;
}
std::string boardhex(){std::ostringstream s;s<<std::hex<<std::setfill('0');for(int i=64;i<128;i++)s<<std::setw(2)<<int(m.ram[i]);return s.str();}
void symbol(char p){switch(p){
case 'K':m.digit(1);break;case 'Q':m.digit(2);break;case 'R':m.digit(3);break;
case 'B':m.digit(5);break;case 'N':m.digit(6);break;case 'P':m.digit(7);break;
case 'k':m.digit(9);break;case 'q':m.digit(0);break;case 'r':m.press(3,4);break;
case 'b':m.press(4,1);break;case 'n':m.press(4,2);break;case 'p':m.press(4,4);break;
default:throw std::runtime_error("Invalid piece symbol");}}
int code(char c){switch(c){case 'P':return 1;case 'N':return 2;case 'B':return 3;case 'R':return 4;case 'Q':return 5;case 'K':return 6;}if(c>='a'&&c<='z')return -code(c-'a'+'A');return 0;}
void setup(const std::string&fen){
 std::istringstream f(fen);std::string pieces,turn,castling,ep;f>>pieces>>turn>>castling>>ep;
 if(turn!="w"&&turn!="b")throw std::runtime_error("Invalid FEN side to move");
 std::array<char,64>b{};int rank=7,file=0;
 for(char c:pieces){if(c=='/'){if(file!=8||rank<=0)throw std::runtime_error("FEN width");--rank;file=0;}else if(c>='1'&&c<='8'){file+=c-'0';}else{if(file>=8||rank<0)throw std::runtime_error("FEN square");code(c);b[rank*8+file++]=c;}}
 if(rank!=0||file!=8)throw std::runtime_error("Incomplete FEN");
 m=F8("@embedded");candidate_ready=false;m.run(4000000);m.level("999999");
 m.press(4,1); // FP, original machine's find-position mode
 for(char c:std::string("KQRRBBNNPPPPPPPPkqrrbbnnpppppppp")){symbol(c);m.press(3,8);}
 m.press(4,8);
 for(int i=64;i<128;i++)if(m.ram[i])throw std::runtime_error("FP/CE did not clear original ROM board");
 for(int q=0;q<64;q++)if(b[q]){
  m.press(4,2);symbol(b[q]);m.digit(q%8+1);m.digit(q/8+1);m.press(4,8);
 }
 for(int q=0;q<64;q++)if(m.ram[64+q]!=u8(code(b[q])))throw std::runtime_error("ROM board differs from FEN at square "+std::to_string(q));
 // At reset the machine plays Black; a Black setup move requires it to play White.
 if(turn=="b")m.press(4,4);
 search_start=m.cycles;std::cout<<"ready board_hex="<<boardhex()<<" computer_color="<<(m.regs[1]==0?"white":"black")<<" rom=extended-time-one-byte level=999999\n"<<std::flush;
}

void watch_move(const std::string& target){
 if(target.size()!=4 && target.size()!=5)throw std::runtime_error("watch requires 4- or 5-char UCI move");
 // The genuine ROM promotes its own pawn to queen. Coordinates alone are
 // not evidence of underpromotion, so never award a false underpromotion win.
 // Underpromotion positions still receive genuine search and 99s exposure.
 bool verifiable=(target.size()==4 || target[4]=='q');
 for(int k=0;k<4;k++)m.flash_target[k]=target[k];
 m.flash_target[4]=0;
 m.flash_armed=verifiable;m.flash_seen=false;m.flash_cycle=m.cycles;
 std::cout<<"watching "<<target<<" board_hex="<<boardhex()<<"\n"<<std::flush;
}
void advance_search(double emulated_seconds){
 if(!std::isfinite(emulated_seconds)||emulated_seconds<=0||emulated_seconds>7200)
   throw std::runtime_error("Invalid slice seconds");
 uint64_t amount=uint64_t(std::llround(emulated_seconds*2000000.));
 auto begin=m.cycles;
 while(amount){uint64_t chunk=std::min<uint64_t>(amount,200000);m.run(chunk);amount-=chunk;
   if(m.flash_seen)break;}
 std::cout<<"advanced seconds="<<double(m.cycles-begin)/2000000
  <<" current_clock_bcd="<<std::hex<<int(m.regs[17])<<":"
  <<int(m.regs[19])<<":"<<int(m.regs[21])<<std::dec
  <<" board_hex="<<boardhex()<<" illegal_opcodes="<<m.illegal_count
  <<" flash_seen="<<(m.flash_seen?1:0)<<" flash_cycle="<<m.flash_cycle<<"\n"<<std::flush;
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
void commit_found(const std::string& u){
 if(!candidate_ready)throw std::runtime_error("Probe required before commit");
 if(u.size()!=4)throw std::runtime_error("Only four-character move supported");
 candidate.press(3,8,.15); // cancel the current ROM proposal
 candidate.move(u); // enter observed reference move via genuine keypad
 m=candidate;candidate_ready=false;
 m.level("999999");m.flash_armed=false;m.flash_seen=false;
 std::cout<<"committed "<<u<<" board_hex="<<boardhex()
   <<" clock_bcd="<<std::hex<<int(m.regs[17])<<":"
   <<int(m.regs[19])<<":"<<int(m.regs[21])<<std::dec<<"\n"<<std::flush;
}
void adopt(){
 if(!candidate_ready)throw std::runtime_error("No verified candidate to adopt");
 if(candidate.rom!=embedded_rom)throw std::runtime_error("Wrong experimental ROM");
 m=candidate;candidate_ready=false;
 // The time-set+CE probe resets its time setting. Restore frozen 999999
 // before the next opponent input and the next solver search.
 m.level("999999");m.flash_armed=false;m.flash_seen=false;
 std::cout<<"adopted board_hex="<<boardhex()<<" clock_bcd="<<std::hex<<int(m.regs[17])<<":"<<int(m.regs[19])<<":"<<int(m.regs[21])<<std::dec<<"\n"<<std::flush;
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
     // Preserve the watch armed before entering the final human move.
     // The ROM may display its correct reply during the ENTER keypress.
     m.move(u);candidate_ready=false;search_start=m.cycles;
     std::cout<<"played "<<u<<" board_hex="<<boardhex()
       <<" input_accepted="<<((m.regs[6]&0x50)==0x50?0:1)
       <<" flash_seen="<<(m.flash_seen?1:0)
       <<" flags="<<int(m.regs[6])<<"\n"<<std::flush;
    }
    else if(line.rfind("watch ",0)==0)watch_move(line.substr(6));
    else if(line.rfind("advance ",0)==0)advance_search(std::stod(line.substr(8)));
    else if(line=="probe")probe();
    else if(line.rfind("commit ",0)==0)commit_found(line.substr(7));
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