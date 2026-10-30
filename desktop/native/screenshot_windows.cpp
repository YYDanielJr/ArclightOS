// SPDX-License-Identifier: GPL-3.0-or-later
#include "screenshot_windows.hpp"
#include "../generated/ext-foreign-toplevel-list.h"
#include "../generated/ext-image-capture-source.h"
#include "../generated/ext-image-copy-capture.h"
#include <wayland-client.h>
#include <X11/Xlib.h>
#include <X11/Xatom.h>
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>
#include <poll.h>
#include <set>
#include <sys/mman.h>
#include <unistd.h>
namespace yy {
namespace {
struct Capture {
  wl_display *display=nullptr; wl_registry *registry=nullptr; wl_shm *shm=nullptr;
  ext_foreign_toplevel_list_v1 *list=nullptr;
  ext_foreign_toplevel_image_capture_source_manager_v1 *sources=nullptr;
  ext_image_copy_capture_manager_v1 *copies=nullptr;
  struct Window {
    ext_foreign_toplevel_handle_v1 *handle;
    std::string title;
    bool closed=false;
  };
  std::vector<std::unique_ptr<Window>> windows;
  ~Capture(){
    for(auto &w:windows)ext_foreign_toplevel_handle_v1_destroy(w->handle);
    if(list)ext_foreign_toplevel_list_v1_destroy(list);
    if(copies)ext_image_copy_capture_manager_v1_destroy(copies);
    if(sources)ext_foreign_toplevel_image_capture_source_manager_v1_destroy(sources);
    if(shm)wl_shm_destroy(shm);
    if(registry)wl_registry_destroy(registry);
    if(display)wl_display_disconnect(display);
  }
  bool wait(bool &done,int ms=600){
    auto deadline=g_get_monotonic_time()+ms*1000;
    while(!done && g_get_monotonic_time()<deadline){
      if(wl_display_dispatch_pending(display)<0)return false;
      if(done)break;
      wl_display_flush(display);
      pollfd fd{wl_display_get_fd(display),POLLIN,0};
      if(poll(&fd,1,20)>0 && wl_display_dispatch(display)<0)return false;
    }
    return done;
  }
  bool sync(){
    bool done=false;auto cb=wl_display_sync(display);
    static const wl_callback_listener listener={+[](void *p,wl_callback *,uint32_t){*static_cast<bool *>(p)=true;}};
    wl_callback_add_listener(cb,&listener,&done);bool result=wait(done);wl_callback_destroy(cb);return result;
  }
  bool init(){
    display=wl_display_connect(nullptr);if(!display)return false;
    registry=wl_display_get_registry(display);
    static const wl_registry_listener registry_events={
      +[](void *p,wl_registry *r,uint32_t n,const char *name,uint32_t){auto c=static_cast<Capture *>(p);
        if(!strcmp(name,"wl_shm"))c->shm=static_cast<wl_shm *>(wl_registry_bind(r,n,&wl_shm_interface,1));
        if(!strcmp(name,"ext_image_copy_capture_manager_v1"))c->copies=static_cast<ext_image_copy_capture_manager_v1 *>(wl_registry_bind(r,n,&ext_image_copy_capture_manager_v1_interface,1));
        if(!strcmp(name,"ext_foreign_toplevel_image_capture_source_manager_v1"))c->sources=static_cast<ext_foreign_toplevel_image_capture_source_manager_v1 *>(wl_registry_bind(r,n,&ext_foreign_toplevel_image_capture_source_manager_v1_interface,1));
        if(!strcmp(name,"ext_foreign_toplevel_list_v1")){
          c->list=static_cast<ext_foreign_toplevel_list_v1 *>(wl_registry_bind(r,n,&ext_foreign_toplevel_list_v1_interface,1));
          static const ext_foreign_toplevel_list_v1_listener list_events={
            +[](void *p,ext_foreign_toplevel_list_v1 *,ext_foreign_toplevel_handle_v1 *h){auto c=static_cast<Capture *>(p);
              auto w=std::make_unique<Window>();w->handle=h;
              static const ext_foreign_toplevel_handle_v1_listener events={
                +[](void *p,ext_foreign_toplevel_handle_v1 *){static_cast<Window *>(p)->closed=true;},
                +[](void *,ext_foreign_toplevel_handle_v1 *){},
                +[](void *p,ext_foreign_toplevel_handle_v1 *,const char *s){static_cast<Window *>(p)->title=s;},
                +[](void *,ext_foreign_toplevel_handle_v1 *,const char *){},
                +[](void *,ext_foreign_toplevel_handle_v1 *,const char *){}};
              ext_foreign_toplevel_handle_v1_add_listener(h,&events,w.get());c->windows.push_back(std::move(w));},
            +[](void *,ext_foreign_toplevel_list_v1 *){}};
          ext_foreign_toplevel_list_v1_add_listener(c->list,&list_events,c);
        }
      },+[](void *,wl_registry *,uint32_t){}};
    wl_registry_add_listener(registry,&registry_events,this);
    return sync()&&sync()&&shm&&copies&&sources&&list;
  }
  cairo_surface_t *capture(Window &w){
    struct Frame {
      uint32_t width=0,height=0,format=UINT32_MAX,transform=0;
      bool constraints=false,finished=false,ready=false;
    } f;
    auto source=ext_foreign_toplevel_image_capture_source_manager_v1_create_source(sources,w.handle);
    auto session=ext_image_copy_capture_manager_v1_create_session(copies,source,0);
    static const ext_image_copy_capture_session_v1_listener events={
      +[](void *p,ext_image_copy_capture_session_v1 *,uint32_t w,uint32_t h){auto f=static_cast<Frame *>(p);f->width=w;f->height=h;},
      +[](void *p,ext_image_copy_capture_session_v1 *,uint32_t format){if(format==WL_SHM_FORMAT_ARGB8888||format==WL_SHM_FORMAT_XRGB8888)static_cast<Frame *>(p)->format=format;},
      +[](void *,ext_image_copy_capture_session_v1 *,wl_array *){},
      +[](void *,ext_image_copy_capture_session_v1 *,uint32_t,wl_array *){},
      +[](void *p,ext_image_copy_capture_session_v1 *){static_cast<Frame *>(p)->constraints=true;},
      +[](void *p,ext_image_copy_capture_session_v1 *){auto f=static_cast<Frame *>(p);f->constraints=true;f->finished=true;}};
    ext_image_copy_capture_session_v1_add_listener(session,&events,&f);
    cairo_surface_t *result=nullptr;
    if(wait(f.constraints)&&!f.finished&&f.width>0&&f.height>0&&f.width<12000&&f.height<12000&&f.format!=UINT32_MAX&&uint64_t(f.width)*f.height<32000000){
      size_t bytes=size_t(f.width)*f.height*4;int fd=memfd_create("arclight-window",MFD_CLOEXEC);
      if(fd>=0 && ftruncate(fd,bytes)==0){
        auto mem=mmap(nullptr,bytes,PROT_READ|PROT_WRITE,MAP_SHARED,fd,0);
        if(mem!=MAP_FAILED){
          auto pool=wl_shm_create_pool(shm,fd,bytes);
          auto buffer=wl_shm_pool_create_buffer(pool,0,f.width,f.height,f.width*4,f.format);
          auto frame=ext_image_copy_capture_session_v1_create_frame(session);
          static const ext_image_copy_capture_frame_v1_listener frame_events={
            +[](void *p,ext_image_copy_capture_frame_v1 *,uint32_t t){static_cast<Frame *>(p)->transform=t;},
            +[](void *,ext_image_copy_capture_frame_v1 *,int32_t,int32_t,int32_t,int32_t){},
            +[](void *,ext_image_copy_capture_frame_v1 *,uint32_t,uint32_t,uint32_t){},
            +[](void *p,ext_image_copy_capture_frame_v1 *){auto f=static_cast<Frame *>(p);f->ready=f->finished=true;},
            +[](void *p,ext_image_copy_capture_frame_v1 *,uint32_t){static_cast<Frame *>(p)->finished=true;}};
          ext_image_copy_capture_frame_v1_add_listener(frame,&frame_events,&f);
          ext_image_copy_capture_frame_v1_attach_buffer(frame,buffer);
          ext_image_copy_capture_frame_v1_damage_buffer(frame,0,0,f.width,f.height);
          ext_image_copy_capture_frame_v1_capture(frame);
          if(wait(f.finished)&&f.ready&&f.transform==WL_OUTPUT_TRANSFORM_NORMAL){
            result=cairo_image_surface_create(CAIRO_FORMAT_RGB24,f.width,f.height);
            memcpy(cairo_image_surface_get_data(result),mem,bytes);cairo_surface_mark_dirty(result);
          }
          ext_image_copy_capture_frame_v1_destroy(frame);wl_buffer_destroy(buffer);wl_shm_pool_destroy(pool);munmap(mem,bytes);
        }
      }
      if(fd>=0)close(fd);
    }
    ext_image_copy_capture_session_v1_destroy(session);ext_image_capture_source_v1_destroy(source);return result;
  }
};
static bool similar(uint32_t a,uint32_t b,int tolerance=12){
  for(int shift:{0,8,16})if(std::abs(int((a>>shift)&255)-int((b>>shift)&255))>tolerance)return false;
  return true;
}
}
J screenshot_match(cairo_surface_t *desktop,cairo_surface_t *window){
  int sw=cairo_image_surface_get_width(desktop),sh=cairo_image_surface_get_height(desktop),
      w=cairo_image_surface_get_width(window),h=cairo_image_surface_get_height(window);
  if(w<40||h<30||w>sw||h>sh)return nullptr;
  cairo_surface_flush(desktop);cairo_surface_flush(window);
  auto s=reinterpret_cast<uint32_t *>(cairo_image_surface_get_data(desktop));
  auto t=reinterpret_cast<uint32_t *>(cairo_image_surface_get_data(window));
  int ss=cairo_image_surface_get_stride(desktop)/4,ts=cairo_image_surface_get_stride(window)/4;
  std::vector<std::pair<int,int>> points;
  for(int y=1;y<=7;++y)for(int x=1;x<=7;++x)points.push_back({x*(w-1)/8,y*(h-1)/8});
  // Include decoration and content edges to distinguish uniform app backgrounds.
  for(int x:{2,w/4,w/2,3*w/4,w-3})for(int y:{2,10,h-3})points.push_back({x,y});
  std::set<uint32_t> colors;for(auto [x,y]:points)colors.insert(t[y*ts+x]&0xf8f8f8);
  if(colors.size()<4)return nullptr;
  auto [ax,ay]=points.front();
  // Pick a high-contrast anchor rather than scanning a common flat background.
  for(auto [x,y]:points)if(!similar(t[y*ts+x],t[(h/2)*ts+w/2],40)){ax=x;ay=y;break;}
  int best=0,bx=0,by=0,matches=0;
  for(int y=0;y<=sh-h;++y)for(int x=0;x<=sw-w;++x){
    if(!similar(s[(y+ay)*ss+x+ax],t[ay*ts+ax]))continue;
    int score=0,miss=0;
    for(auto [px,py]:points){if(similar(s[(y+py)*ss+x+px],t[py*ts+px]))++score;else if(++miss>4)break;}
    if(score>best){best=score;bx=x;by=y;matches=1;}
    else if(score==best&&score>=int(points.size())-4 && (std::abs(x-bx)>2||std::abs(y-by)>2))++matches;
  }
  if(best<int(points.size())-4||matches>1)return nullptr;
  return J{{"x",bx},{"y",by},{"width",w},{"height",h}};
}
std::string screenshot_windows(cairo_surface_t *desktop,int ox,int oy,const std::vector<double> &scales){
  std::string output;std::set<std::string> seen;
  auto add=[&](int x,int y,int w,int h,std::string title){
    if(w<20||h<20)return;
    auto geometry=std::to_string(x)+","+std::to_string(y)+" "+std::to_string(w)+"x"+std::to_string(h);
    if(!seen.insert(geometry).second)return;
    replace(title,"\n"," ");replace(title,"\r"," ");output+=geometry+" "+title+"\n";
  };
  // XWayland exposes exact client bounds. Include compositor frame extents
  // when available; image matching below also handles native Wayland windows.
  if(auto d=XOpenDisplay(nullptr)) {
    auto root=DefaultRootWindow(d);Window root_return,parent,*children=nullptr;unsigned count=0;
    if(XQueryTree(d,root,&root_return,&parent,&children,&count)) {
      for(unsigned i=0;i<count;++i) {
        XWindowAttributes a{};if(!XGetWindowAttributes(d,children[i],&a)||a.map_state!=IsViewable||a.override_redirect||a.width<40||a.height<30)continue;
        int x,y;Window child;XTranslateCoordinates(d,children[i],root,0,0,&x,&y,&child);
        char *title=nullptr;XFetchName(d,children[i],&title);
        add(x,y,a.width,a.height,title?title:"XWayland");if(title)XFree(title);
      }
      if(children)XFree(children);
    }
    XCloseDisplay(d);
  }
  Capture capture;
  if(capture.init()){
    auto deadline=g_get_monotonic_time()+2500000;
    for(auto &window:capture.windows){
      if(window->closed||g_get_monotonic_time()>deadline)continue;
      auto image=capture.capture(*window);if(!image)continue;
      std::vector<double> ratios={1};for(auto v:scales)if(v!=1)ratios.push_back(v);
      for(auto scale:ratios){
        auto scaled=cairo_image_surface_create(CAIRO_FORMAT_RGB24,std::lround(cairo_image_surface_get_width(image)/scale),std::lround(cairo_image_surface_get_height(image)/scale));
        auto cr=cairo_create(scaled);cairo_scale(cr,1/scale,1/scale);cairo_set_source_surface(cr,image,0,0);cairo_paint(cr);cairo_destroy(cr);
        auto match=screenshot_match(desktop,scaled);cairo_surface_destroy(scaled);
        if(!match.is_null()){add(ox+match["x"].get<int>(),oy+match["y"].get<int>(),match["width"],match["height"],window->title);break;}
      }
      cairo_surface_destroy(image);
    }
  }
  return output;
}
} // namespace yy
