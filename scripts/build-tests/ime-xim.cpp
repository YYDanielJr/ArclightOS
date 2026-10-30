// SPDX-License-Identifier: GPL-3.0-or-later
// Run only inside the private compositor launched by test-desktop-update.sh.
#include <X11/Xlib.h>
#include <X11/keysym.h>
#include <chrono>
#include <clocale>
#include <cstdlib>
#include <iostream>
#include <thread>
int main(){
  setlocale(LC_ALL,"C.UTF-8");
  if(!XSetLocaleModifiers("")){std::cerr<<"Invalid XMODIFIERS\n";return 1;}
  auto d=XOpenDisplay(nullptr);if(!d){std::cerr<<"No private XWayland display\n";return 1;}
  auto w=XCreateSimpleWindow(d,DefaultRootWindow(d),40,40,420,180,1,0,0xffffff);
  XStoreName(d,w,"Arclight isolated XIM input test");XSelectInput(d,w,KeyPressMask|KeyReleaseMask|FocusChangeMask|ExposureMask|StructureNotifyMask);
  XMapWindow(d,w);XSync(d,False);
  auto gc=XCreateGC(d,w,0,nullptr);XSetForeground(d,gc,0xf0f0f0);XFillRectangle(d,w,gc,0,0,420,180);XSync(d,False);
  XIM im=nullptr;
  for(int i=0;i<50&&!im;++i){im=XOpenIM(d,nullptr,nullptr,nullptr);if(!im)std::this_thread::sleep_for(std::chrono::milliseconds(100));}
  if(!im){std::cerr<<"Fcitx XIM frontend unavailable\n";return 1;}
  auto ic=XCreateIC(im,XNInputStyle,XIMPreeditNothing|XIMStatusNothing,XNClientWindow,w,XNFocusWindow,w,nullptr);
  if(!ic){std::cerr<<"XCreateIC failed\n";return 1;}
  std::this_thread::sleep_for(std::chrono::milliseconds(300));XEvent active{};active.xclient.type=ClientMessage;active.xclient.window=w;
  active.xclient.message_type=XInternAtom(d,"_NET_ACTIVE_WINDOW",False);active.xclient.format=32;active.xclient.data.l[0]=2;
  XSendEvent(d,DefaultRootWindow(d),False,SubstructureRedirectMask|SubstructureNotifyMask,&active);
  XSetInputFocus(d,w,RevertToParent,CurrentTime);XSetICFocus(ic);XFlush(d);
  // Process focus notifications before activating Pinyin.
  auto pump=[&](int ms,std::string &committed){auto stop=std::chrono::steady_clock::now()+std::chrono::milliseconds(ms);
    while(std::chrono::steady_clock::now()<stop){while(XPending(d)){XEvent e;XNextEvent(d,&e);if(XFilterEvent(&e,None))continue;
      if(e.type==KeyPress){char buf[1024];KeySym sym;Status status;auto n=Xutf8LookupString(ic,&e.xkey,buf,sizeof buf,&sym,&status);
        if(status==XLookupChars||status==XLookupBoth)committed.append(buf,n);}}
      std::this_thread::sleep_for(std::chrono::milliseconds(2));}};
  std::string committed;pump(300,committed);
  if(std::system("fcitx5-remote -s pinyin")!=0||std::system("fcitx5-remote -o")!=0)return 1;
  pump(300,committed);committed.clear();
  for(auto key:{XK_n,XK_i,XK_h,XK_a,XK_o,XK_space}){
    auto code=XKeysymToKeycode(d,key);
    XEvent event{};event.xkey.display=d;event.xkey.window=w;event.xkey.root=DefaultRootWindow(d);
    event.xkey.same_screen=True;event.xkey.keycode=code;event.xkey.time=CurrentTime;
    event.xkey.type=KeyPress;XSendEvent(d,w,False,KeyPressMask,&event);
    event.xkey.type=KeyRelease;XSendEvent(d,w,False,KeyReleaseMask,&event);
    XFlush(d);pump(120,committed);
  }
  pump(1500,committed);XUnsetICFocus(ic);XDestroyIC(ic);XCloseIM(im);XFreeGC(d,gc);XDestroyWindow(d,w);XCloseDisplay(d);
  bool chinese=false;for(unsigned char c:committed)chinese|=c>=0x80;
  if(!chinese){std::cerr<<"No Chinese XIM commit; received: "<<committed<<'\n';return 1;}
  std::cout<<"PASS Pinyin committed Chinese through XWayland XIM: "<<committed<<'\n';return 0;
}
