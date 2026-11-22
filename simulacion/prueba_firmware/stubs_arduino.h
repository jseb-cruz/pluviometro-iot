#include <cstdio>
#include <cmath>
#include <cstdint>
#include <ctime>
#include <string>
#include <map>
#include <vector>
#include <algorithm>
using std::max; using std::isnan;
struct String { std::string s; String(const char*c=""):s(c){} void trim(){} bool operator==(const char*o)const{return s==o;} String& operator=(const char*c){s=c;return *this;} const char* c_str()const{return s.c_str();} String toString()const{return *this;} };
struct SerialT { void begin(int){} bool available(){return false;} String readStringUntil(char){return String();} void print(const char*){} void println(const char*){} template<class...A> void printf(const char*,A...){} } Serial;
static unsigned long g_ms=0; static std::vector<long> g_raw; static std::vector<double> g_pot; static size_t g_i=0;
inline void delay(int){} inline unsigned long millis(){return g_ms;}
inline void analogReadResolution(int){} inline void analogSetPinAttenuation(int,int){}
inline int analogReadMilliVolts(int){ return (int)lround(g_pot[g_i? g_i-1:0]); }
#define ADC_11db 3
#define WL_CONNECTED 3
#define WIFI_STA 1
struct IP{String toString(){return String();}};
struct WiFiT{int status(){return 3;} void mode(int){} void begin(const char*,const char*){} IP localIP(){return IP();}} WiFi;
struct WiFiClientSecure{void setCACert(const char*){} void setCertificate(const char*){} void setPrivateKey(const char*){}};
struct PubSubClient{PubSubClient(WiFiClientSecure&){} bool connected(){return true;} bool connect(const char*){return true;} int state(){return 0;} void loop(){} void setServer(const char*,int){} bool setBufferSize(int){return true;} bool publish(const char*,const char*p,size_t){ std::printf("%s\n",p); return true;}};
inline void configTime(int,int,const char*,const char*){}
// El HX711 entrega la senal del gemelo; el reloj avanza 100 ms (10 SPS) por muestra
struct HX711{void begin(int,int){} bool is_ready(){return g_i<g_raw.size();} long read(){ g_ms+=100; return g_raw[g_i++];} long read_average(int){return 0;}};
struct JV{ std::string v; template<class T> JV& operator=(T x){ char b[64]; std::snprintf(b,64,"%.6g",(double)x); v=b; return *this;} JV& operator=(const String&x){ v="\""+x.s+"\""; return *this;} JV& operator=(bool x){ v=x?"true":"false"; return *this;} };
struct JsonDocument{ std::vector<std::pair<std::string,JV>> kv; JV& operator[](const char*k){ kv.push_back({k,JV()}); return kv.back().second;} };
inline size_t serializeJson(JsonDocument&d,char*buf){ std::string s="{"; for(size_t i=0;i<d.kv.size();i++){ if(i) s+=","; s+="\""+d.kv[i].first+"\":"+d.kv[i].second.v;} s+="}"; std::snprintf(buf,512,"%s",s.c_str()); return s.size();}
