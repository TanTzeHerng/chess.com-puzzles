// Separate puzzle adapter. Chess moves and evaluations come only from the unchanged ROM.
#include "f8_standalone.h"
#include <sstream>
#include <thread>
#include <filesystem>
#include <type_traits>
F8 m("@embedded");
std::string checkpoint_path;
void checkpoint(){
 if(checkpoint_path.empty())return;
 static_assert(std::is_trivially_copyable<F8>::value,"Checkpoint requires pointer-free emulated state");
 std::ofstream f(checkpoint_path+".tmp",std::ios::binary|std::ios::trunc);
 uint64_t size=sizeof(F8);f.write("D1PZCP01",8);f.write((char*)&size,8);f.write((char*)&m,sizeof(m));f.close();
 if(!f)throw std::runtime_error("Checkpoint write failed");std::filesystem::rename(checkpoint_path+".tmp",checkpoint_path);
}
void load_checkpoint(const std::string&p){
 std::ifstream f(p,std::ios::binary);char magic[8];uint64_t size=0;f.read(magic,8);f.read((char*)&size,8);
 if(!f||std::string(magic,8)!="D1PZCP01"||size!=sizeof(F8))throw std::runtime_error("Incompatible checkpoint");
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
 if((turn!="w"&&turn!="b")||castling!="-"||ep!="-")throw std::runtime_error("This verified keypad loader requires no castling or EP rights");
 std::array<char,64>b{};int rank=7,file=0;
 for(char c:pieces){if(c=='/'){if(file!=8||rank<=0)throw std::runtime_error("FEN width");--rank;file=0;}else if(c>='1'&&c<='8'){file+=c-'0';}else{if(file>=8||rank<0)throw std::runtime_error("FEN square");code(c);b[rank*8+file++]=c;}}
 if(rank!=0||file!=8)throw std::runtime_error("Incomplete FEN");
 m=F8("@embedded");m.run(4000000);m.level("009999");
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
 std::cout<<"ready board_hex="<<boardhex()<<" computer_color="<<(m.regs[1]==0?"white":"black")<<" original_rom=unchanged level=009999\n"<<std::flush;
}
void go(){
 auto start=std::chrono::steady_clock::now(),last=start,last_cp=start;uint64_t begin=m.cycles;
 std::string prior,answer;int stable=0;
 while(m.cycles-begin<2000000ull*(6039ull*4+120)){
  m.run(20000);auto s=m.display();
  bool coord=s.size()==4&&s[0]>='a'&&s[0]<='h'&&s[1]>='1'&&s[1]<='8'&&s[2]>='a'&&s[2]<='h'&&s[3]>='1'&&s[3]<='8';
  if((m.regs[6]&8)&&coord){stable=s==prior?stable+1:0;prior=s;if(stable>=4){answer=s;break;}}else stable=0;
  auto now=std::chrono::steady_clock::now();if(std::chrono::duration<double>(now-last).count()>5){std::cout<<"info emulated_seconds="<<double(m.cycles-begin)/2000000<<" wall_seconds="<<std::chrono::duration<double>(now-start).count()<<"\n"<<std::flush;last=now;}
  if(std::chrono::duration<double>(now-last_cp).count()>30){checkpoint();last_cp=now;}
 }
 auto wall=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
 std::cout<<"info completed_board_hex="<<boardhex()<<" flags="<<int(m.regs[6])<<" computer="<<int(m.regs[1])<<" cycles="<<m.cycles<<" wall_seconds="<<wall<<" illegal_opcodes="<<m.illegal_count<<"\n";
 std::cout<<"bestmove "<<(answer.empty()?"0000":answer)<<"\n"<<std::flush;
}
int main(int argc,char**argv){try{for(int i=1;i<argc;i++)if(std::string(argv[i])=="--checkpoint"&&i+1<argc)checkpoint_path=argv[++i];std::string line;while(std::getline(std::cin,line)){
 if(line.rfind("setup ",0)==0)setup(line.substr(6));
 else if(line.rfind("play ",0)==0){std::string u=line.substr(5);if(u.size()!=4)throw std::runtime_error("Only ordinary four-character opponent moves supported");m.move(u);}
 else if(line=="go")go();else if(line=="quit")return 0;
 else if(line.rfind("load ",0)==0)load_checkpoint(line.substr(5));
 else if(line.rfind("set-checkpoint ",0)==0)checkpoint_path=line.substr(15);
 else if(line=="checkpoint"){checkpoint();std::cout<<"checkpoint saved\n"<<std::flush;}
 else if(line=="dump")std::cout<<"dump board_hex="<<boardhex()<<" flags="<<int(m.regs[6])<<" computer="<<int(m.regs[1])<<"\n"<<std::flush;
 }return 0;}catch(const std::exception&e){std::cout<<"error "<<e.what()<<"\n"<<std::flush;return 2;}}
