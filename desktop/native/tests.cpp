// SPDX-License-Identifier: GPL-3.0-or-later
#include "common.hpp"
#include "archive.hpp"
#include "storage.hpp"
#include <archive.h>
#include <archive_entry.h>
#include <zlib.h>
#include <chrono>
#include <iostream>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>
using namespace yy;
static int checks = 0;
static void test(bool ok, const std::string &m) {
  require(ok, m);
  ++checks;
  std::cout << "PASS " << m << '\n';
}
static void rejected(std::function<void()> f, const std::string &m) {
  bool r = false;
  try {
    f();
  } catch (...) {
    r = true;
  }
  test(r, m);
}
int main(int argc, char **argv) {
  try {
    if (argc == 2 && std::string(argv[1]) == "--multihead") {
      auto raw = J::parse(run({"wlr-randr", "--json"}));
      test(raw.size() == 2, "two headless Wayland outputs");
      auto original = display_snapshot(raw), desired = original;
      desired[0]["scale"] = 1.25;
      desired[1]["scale"] = 1.5;
      desired[1]["x"] =
          std::lround(raw[0]["modes"][0]["width"].get<int>() / 1.25);
      auto lease = display_begin(desired, 2);
      auto changed = display_snapshot(J::parse(run({"wlr-randr", "--json"})));
      test(changed[0]["scale"] == 1.25 && changed[1]["scale"] == 1.5 &&
               changed[1]["x"] == desired[1]["x"],
           "mixed scaling and logical positioning");
      std::this_thread::sleep_for(std::chrono::seconds(4));
      test(display_snapshot(J::parse(run({"wlr-randr", "--json"}))) ==
                   original &&
               !fs::exists(lease),
           "independent ELF watchdog restores layout");
      desired = original;
      desired[1]["enabled"] = false;
      lease = display_begin(desired, 2);
      test(!display_snapshot(
                J::parse(run({"wlr-randr", "--json"})))[1]["enabled"]
                .get<bool>(),
           "disable one output");
      std::this_thread::sleep_for(std::chrono::seconds(4));
      test(display_snapshot(J::parse(run({"wlr-randr", "--json"}))) == original,
           "restore disabled output and its mode");
      return 0;
    }
    auto previous_labwc_pid=env("LABWC_PID");bool had_labwc_pid=getenv("LABWC_PID")!=nullptr;
    unsetenv("LABWC_PID");
    rejected([]{labwc_reconfigure();},"reload rejects a missing compositor PID");
    setenv("LABWC_PID","invalid",1);
    rejected([]{labwc_reconfigure();},"reload rejects a malformed compositor PID");
    setenv("LABWC_PID","1",1);
    rejected([]{labwc_reconfigure();},"reload rejects a reserved PID");
    setenv("LABWC_PID",std::to_string(getpid()).c_str(),1);
    rejected([]{labwc_reconfigure();},"reload refuses an unrelated process without signalling it");
    if(had_labwc_pid)setenv("LABWC_PID",previous_labwc_pid.c_str(),1);else unsetenv("LABWC_PID");
    auto bytes=[](std::string text){J result=J::array();for(unsigned char c:text)result.push_back(c);result.push_back(0);return result;};
    J storage=J::object();std::string ud="/org/freedesktop/UDisks2/",ub="org.freedesktop.UDisks2.";
    storage[ud+"drives/usb"][ub+"Drive"]={{"Model","USB Test"},{"ConnectionBus","usb"},{"CanPowerOff",true},{"Size",uint64_t(1024)}};
    storage[ud+"block_devices/sda"][ub+"Block"]={{"Drive",ud+"drives/usb"},{"PreferredDevice",bytes("/dev/sda")},{"Size",uint64_t(1024)}};
    storage[ud+"block_devices/sda"][ub+"PartitionTable"]={{"Type","gpt"}};
    for(auto n:{1,2}) {
      auto path=ud+"block_devices/sda"+std::to_string(n);storage[path][ub+"Block"]={{"Drive",ud+"drives/usb"},{"PreferredDevice",bytes("/dev/sda"+std::to_string(n))},{"IdType","ext4"},{"IdLabel","Part "+std::to_string(n)},{"Size",uint64_t(512)}};
      storage[path][ub+"Partition"]={{"Table",ud+"block_devices/sda"}};storage[path][ub+"Filesystem"]={{"MountPoints",J::array({bytes("/media/test/"+std::to_string(n))})}};
    }
    auto model=storage_model(storage);
    test(model.size()==1 && model[0]["parts"].size()==2,"storage groups partitions beneath one physical drive");
    test(model[0]["icon"]=="drive-removable-media-usb" && model[0]["device"]=="/dev/sda","storage identifies USB drive and decodes device bytes");
    test(model[0]["parts"][0]["mounted"].get<bool>() && !model[0]["parts"][0]["usage_known"].get<bool>(),"storage distinguishes mounted state from unknown usage");
    test(storage_eject_plan(model,ud+"drives/usb").size()==1,"safe eject plans all partitions of the target drive");
    auto protected_storage=storage;protected_storage[ud+"block_devices/sda1"][ub+"Filesystem"]["MountPoints"]=J::array({bytes("/")});
    protected_storage[ud+"block_devices/sda1"][ub+"Block"]["HintIgnore"]=true;
    auto system_model=storage_model(protected_storage);
    rejected([&]{storage_eject_plan(system_model,ud+"drives/usb");},"reject eject of a drive containing root even when automount ignores it");
    protected_storage=storage;protected_storage[ud+"block_devices/sda2"][ub+"Swapspace"]={{"Active",true}};
    rejected([&]{storage_eject_plan(storage_model(protected_storage),ud+"drives/usb");},"reject eject of a drive with active swap");
    auto siblings=model;auto second=model[0];second["path"]=ud+"drives/usb2";model[0]["sibling"]="reader";second["sibling"]="reader";siblings=J::array({model[0],second});
    test(storage_eject_plan(siblings,ud+"drives/usb").size()==2,"safe eject includes sibling drives sharing one USB reader");
    siblings[1]["protected"]=true;rejected([&]{storage_eject_plan(siblings,ud+"drives/usb");},"reject eject when a sibling drive is used by the system");
    auto encrypted_storage=storage;auto crypto=ud+"block_devices/dm_2d0";encrypted_storage[crypto][ub+"Block"]={{"Drive","/"},{"PreferredDevice",bytes("/dev/dm-0")},{"CryptoBackingDevice",ud+"block_devices/sda2"},{"Size",uint64_t(500)}};encrypted_storage[crypto][ub+"Filesystem"]={{"MountPoints",J::array()}};
    test(storage_model(encrypted_storage)[0]["parts"].size()==3,"storage attaches an unlocked crypto child to its physical drive");
    test(storage_size(1024)=="1.0 KiB","storage uses consistent binary capacity units");
    J items = J::array({{{"name", "HEADLESS-1"},
                         {"description", "Test monitor"},
                         {"enabled", true},
                         {"mode", "1920x1080@60.000000Hz"},
                         {"scale", 1.25},
                         {"x", 0},
                         {"y", 0},
                         {"transform", "normal"}}});
    test(display_command(items).size() == 12, "display argument construction");
    auto bad = items;
    bad[0]["enabled"] = false;
    rejected([&] { display_validate(bad); }, "reject all outputs disabled");
    bad = items;
    bad[0]["scale"] = 0;
    rejected([&] { display_validate(bad); }, "reject invalid scaling");
    bad = items;
    bad[0]["name"] = "x;touch /tmp/no";
    rejected([&] { display_validate(bad); }, "reject connector injection");
    bad = items;
    bad[0]["description"] = "hello\noutput injected";
    rejected([&] { display_validate(bad); }, "reject kanshi newline injection");
    auto profile = profile_text(J{{"one", items}});
    test(profile.find("scale 1.250000") != profile.npos,
         "fractional kanshi profile");
    test(profile.find("output \"HEADLESS-1\"") != profile.npos &&
             profile.find("Test monitor") == profile.npos,
         "kanshi profile uses connector name");
    bad = items;
    bad.push_back(items[0]);
    bad[1]["name"] = "HEADLESS-2";
    profile = profile_text(J{{"two", bad}});
    test(profile.find("\"HEADLESS-1\"") != profile.npos &&
             profile.find("\"HEADLESS-2\"") != profile.npos,
         "duplicate EDIDs use connectors");
    rejected([] { validate_policy("install", {{"component", "foo;id"}}); },
             "reject arbitrary packages");
    rejected(
        [] {
          validate_policy("service", {{"name", "sshd;id"}, {"enabled", true}});
        },
        "reject arbitrary services");
    rejected(
        [] { validate_policy("service", {{"name", "ssh"}, {"enabled", 1}}); },
        "reject coerced boolean");
    rejected([] { validate_policy("apt-refresh", {{"command", "id"}}); },
             "reject extra helper keys");
    rejected(
        [] {
          validate_policy(
              "firewall-rule",
              {{"port", 65536}, {"protocol", "tcp"}, {"allow", true}});
        },
        "reject invalid ports");
    rejected(
        [] {
          validate_policy("apt-proxy",
                          {{"url", "http://user:secret@host:7897"}});
        },
        "reject proxy credentials");
    rejected(
        [] {
          validate_policy("apt-proxy",
                          {{"url", "http://host:7897\nInclude /tmp/config"}});
        },
        "reject APT injection");
    rejected(
        [] {
          validate_policy("raspi",
                          {{"option", "boot-rom"}, {"value", "E1;id"}});
        },
        "reject raspi-config injection");
    validate_policy("service", {{"name", "ssh"}, {"enabled", true}});
    test(true, "enumerated service accepted");
    rejected([] { validate_policy("iso-upgrade-check",{{"iso","/tmp/update.iso"},{"sha256","abcd"}}); },
             "reject incomplete trusted ISO digest");
    rejected([] { validate_policy("iso-upgrade",{{"iso","/tmp/update.iso"},{"sha256",std::string(64,'a')},{"plan",";id"}}); },
             "reject injected upgrade plan");
    rejected([] { validate_policy("iso-upgrade-check",{{"iso","relative.iso"},{"sha256",std::string(64,'a')}}); },
             "reject relative ISO path");
    validate_policy("bundle-upgrade-check",{{"bundle","/tmp/update.tar.xz"},{"sha256",std::string(64,'a')}});
    test(true,"compressed update policy accepts an absolute input with complete digest");
    rejected([]{validate_policy("bundle-upgrade-check",{{"bundle","relative.tar.xz"},{"sha256",std::string(64,'a')}});},
             "compressed update rejects a relative archive path");
    rejected([]{validate_policy("bundle-upgrade",{{"bundle","/tmp/update.tar.xz"},{"sha256",std::string(64,'a')},{"plan","stale"}});},
             "compressed update rejects an invalid plan token");
    auto touch = J{{"naturalScroll","yes"},{"tap","yes"},{"tapAndDrag","yes"},
       {"dragLock","no"},{"disableWhileTyping","yes"},{"leftHanded","no"},
       {"scrollMethod","twofinger"},{"clickMethod","clickfinger"},
       {"accelProfile","adaptive"},{"pointerSpeed",.25}};
    auto xml = touchpad_xml("<labwc_config><keyboard><keybind key=\"W-r\"/></keyboard>"
        "<libinput><device category=\"mouse\"><naturalScroll>no</naturalScroll></device>"
        "<device category=\"touchpad\"><tap>no</tap><custom>keep</custom></device>"
        "</libinput></labwc_config>", touch);
    test(xml.find("keybind key=\"W-r\"")!=xml.npos && xml.find("<custom>keep</custom>")!=xml.npos &&
         xml.find("<naturalScroll>yes</naturalScroll>")!=xml.npos && xml.find("<naturalScroll>no</naturalScroll>")!=xml.npos,
         "touchpad update preserves keyboard, mouse and unknown options");
    auto evil=touch; evil["pointerSpeed"]=1.01;
    rejected([&] { touchpad_xml("<labwc_config/>",evil); },"reject excessive touchpad speed");
    evil=touch; evil["scrollMethod"]="twofinger</scrollMethod>";
    rejected([&] { touchpad_xml("<labwc_config/>",evil); },"reject touchpad XML injection");
    rejected([&] { touchpad_xml("<!DOCTYPE x [<!ENTITY a SYSTEM 'file:///etc/passwd'>]><labwc_config/>",touch); },
             "reject XML external entity configuration");
    char temp[] = "/tmp/arclight-native-tests-XXXXXX";
    auto dir = mkdtemp(temp);
    require(dir, "temporary directory");
    auto fixture=[&](const fs::path &file,const std::vector<std::string> &names,int special=0) {
      auto archive=archive_write_new();archive_write_set_format_pax_restricted(archive);
      require(archive_write_open_filename(archive,file.c_str())==ARCHIVE_OK,"create update fixture");
      for(auto &name:names) {
        auto entry=archive_entry_new();archive_entry_set_pathname(entry,name.c_str());
        archive_entry_set_perm(entry,0600);archive_entry_set_filetype(entry,special==1?AE_IFLNK:AE_IFREG);
        if(special==1)archive_entry_set_symlink(entry,"../../outside");
        else if(special==2)archive_entry_set_hardlink(entry,"../../outside");
        else archive_entry_set_size(entry,2);
        require(archive_write_header(archive,entry)==ARCHIVE_OK,"write update fixture header");
        if(!special)archive_write_data(archive,"{}",2);
        archive_entry_free(entry);
      }
      archive_write_close(archive);archive_write_free(archive);
    };
    auto update=fs::path(dir)/"update.tar";
    fixture(update,{"upgrade/manifest.json","upgrade/pool/example_1_amd64.deb","sources/retained.tar.xz"});
    auto extracted=fs::path(dir)/"update-content";
    extract_update_bundle(update,extracted,1024);
    test(read(extracted/"upgrade/manifest.json")=="{}" && read(extracted/"upgrade/pool/example_1_amd64.deb")=="{}",
         "native update extraction reads the exact manifest and package bytes");
    test(!fs::exists(extracted/"sources"),"update extraction skips corresponding source payloads");
    fixture(update,{"../outside"});
    rejected([&]{extract_update_bundle(update,fs::path(dir)/"traversal",1024);},"update rejects archive traversal");
    fixture(update,{"/absolute-update-path"});
    rejected([&]{extract_update_bundle(update,fs::path(dir)/"absolute",1024);},"update rejects absolute archive paths");
    fixture(update,{"upgrade/pool/link.deb"},1);
    rejected([&]{extract_update_bundle(update,fs::path(dir)/"links",1024);},"update rejects archive symlinks");
    fixture(update,{"upgrade/pool/link.deb"},2);
    rejected([&]{extract_update_bundle(update,fs::path(dir)/"hardlinks",1024);},"update rejects archive hardlinks");
    fixture(update,{"upgrade/manifest.json","upgrade/manifest.json"});
    rejected([&]{extract_update_bundle(update,fs::path(dir)/"duplicates",1024);},"update rejects duplicate archive files");
    fixture(update,{"upgrade/manifest.json"});
    rejected([&]{extract_update_bundle(update,fs::path(dir)/"oversized",1);},"update enforces the unpacked byte limit");
    setenv("XDG_CONFIG_HOME", dir, 1);
    write(config()/"labwc/rc.xml", "<labwc_config><keyboard><keybind key=\"Print\"><action name=\"Execute\"><command>keep-user-screenshot</command></action></keybind></keyboard></labwc_config>");
    desktop_defaults();
    auto first_defaults=read(config()/"labwc/rc.xml");
    desktop_defaults();
    test(read(config()/"labwc/rc.xml")==first_defaults && first_defaults.find("keep-user-screenshot")!=first_defaults.npos &&
         first_defaults.find("C-A-a")!=first_defaults.npos,
         "desktop defaults preserve occupied screenshot binding and are idempotent");
    auto keys=hotkey_xml("<labwc_config><keyboard><keybind key=\"XF86AudioRaiseVolume\"><action name=\"Execute\" command=\"wfpanelctl volumepulse volu\"/></keybind><keybind key=\"XF86AudioMute\"><action name=\"Execute\"><command>my-custom-mute</command></action></keybind></keyboard><mouse><keep/></mouse></labwc_config>");
    test(keys.find("arclight-osd volume-up")!=keys.npos && keys.find("arclight-osd brightness-down")!=keys.npos && keys.find("arclight-osd mic-mute")!=keys.npos,"OSD upgrades stock audio and adds missing brightness and microphone bindings");
    test(keys.find("my-custom-mute")!=keys.npos && keys.find("arclight-osd volume-mute")==keys.npos && keys.find("<keep/>")!=keys.npos,"OSD preserves user shortcuts and unrelated compositor settings");
    test(hotkey_xml(keys)==keys,"OSD shortcut migration is idempotent");
    test(read(config()/"libfm/libfm.conf").find("x-terminal-emulator %s")!=std::string::npos,
         "file manager receives a default terminal without shell interpolation");
    write(config() / "labwc/environment", "KEEP_VALUE=1\n");
    write(config()/"environment.d/80-yydaniel-input.conf", "GTK_IM_MODULE=\"old\"\n");
    managed_environment("input", {{"GTK_IM_MODULE", "fcitx"}});
    test(!fs::exists(config()/"environment.d/80-yydaniel-input.conf"),
         "renamed environment cannot be overridden by the legacy filename");
    managed_environment("input", {{"GTK_IM_MODULE", "ibus"}});
    auto e = read(config() / "labwc/environment");
    test(e.find("KEEP_VALUE=1") != e.npos && e.find("fcitx") == e.npos &&
             e.find("ibus") != e.npos,
         "preserve user environment and replace managed block");
    test(e.find("GTK_IM_MODULE=ibus\n") != e.npos &&
         e.find("'ibus'") == e.npos,
         "labwc input method values contain no literal shell quotes");
    test(read(config()/"environment.d/80-arclight-input.conf").find(
         "GTK_IM_MODULE=\"ibus\"\n") != std::string::npos,
         "systemd environment has its own serialization");
    write(config()/"labwc/environment","KEEP_VALUE=1\n# BEGIN YYDANIEL input\nGTK_IM_MODULE='fcitx'\nQT_IM_MODULE='fcitx'\nXMODIFIERS='@im=fcitx'\n# END YYDANIEL input\n");
    test(repair_input_environment() && read(config()/"labwc/environment").find("XMODIFIERS=@im=fcitx\n")!=std::string::npos,
         "migrate existing quoted input-method blocks");
    auto migrated=read(config()/"labwc/environment");repair_input_environment();
    test(read(config()/"labwc/environment")==migrated && migrated.find("KEEP_VALUE=1")!=std::string::npos,
         "input-method migration is idempotent and preserves other settings");
    test(migrated.find("# BEGIN ARCLIGHT input")!=migrated.npos && migrated.find("# BEGIN YYDANIEL input")==migrated.npos,
         "input-method migration writes one canonical Arclight block");
    fs::create_directories(config()/"yydaniel");
    test(state()==config()/"yydaniel", "legacy private settings remain accessible after rename");
    fs::create_directories(config()/"arclight");
    test(state()==config()/"arclight", "explicit Arclight settings take precedence over legacy state");
    rejected(
        [] {
          managed_environment("input",
                              {{"GTK_IM_MODULE", "$(touch /tmp/owned)"}});
        },
        "reject environment expansion");
    write(config() / "secret", "password", true);
    struct stat st{};
    stat((config() / "secret").c_str(), &st);
    test((st.st_mode & 0777) == 0600, "private config permissions");
    test(fields("one:two\\:three:four") ==
             std::vector<std::string>({"one", "two:three", "four"}),
         "escaped nmcli fields");
    test(trim(run({"/bin/cat"}, "example")) == "example", "subprocess stdin");
    rejected([] { run({"/bin/sleep", "5"}, "", 1); }, "subprocess timeout");
    fs::path archive_dir=fs::path(dir)/"archive-tests";
    fs::create_directories(archive_dir/"input/子目录");
    write(archive_dir/"input/子目录/a ; $file.txt","archive sample",false,false);
    for(auto format:{"zip","7z","tar.gz"}) {
      auto output=archive_dir/(std::string("sample.")+format);
      archive_create(output,{archive_dir/"input"},format,5,"",{});
      archive_test(output,"",{});
      archive_extract(output,archive_dir/(std::string("out-")+format),"",false,{});
      test(read(archive_dir/(std::string("out-")+format)/"input/子目录/a ; $file.txt")=="archive sample",
           std::string("native archive roundtrip: ")+format);
    }
    for(auto format:{"zip","7z","tar.gz"}) {
      std::vector<ArchiveProgress> updates;
      auto output=archive_dir/(std::string("progress.")+format);
      archive_create(output,{archive_dir/"input"},format,5,"",[&](const ArchiveProgress &p){updates.push_back(p);});
      auto last=updates.back();auto metrics=archive_progress_values(last,2);
      test(last.complete && last.total_known && last.total_bytes==14 && last.processed_bytes==14 &&
           last.files_done==1 && last.files_total==1 && last.output_bytes==fs::file_size(output) && metrics["fraction"]==1.0,
           std::string("actual progress totals, source reads and output size: ")+format);
      bool finalize=false;
      for(auto &p:updates)if(p.phase=="finalize") {
        finalize=true;test(archive_progress_values(p,1)["fraction"]==.99,
          std::string("progress reserves completion until archive publication: ")+format);break;
      }
      test(finalize,std::string("archive reports finalization phase: ")+format);
      auto expected=100.0*fs::file_size(output)/14;
      test(std::abs(metrics["ratio"].get<double>()-expected)<.0001,std::string("compression ratio uses actual output bytes: ")+format);
    }
    ArchiveProgress unknown;unknown.operation="create";
    auto metrics=archive_progress_values(unknown,0);
    test(metrics["fraction"].is_null() && metrics["ratio"].is_null() && metrics["remaining"].is_null(),
         "unknown totals and zero-byte ratios remain unknown");
    unknown.total_known=true;unknown.total_bytes=100;unknown.processed_bytes=25;unknown.phase="process";
    metrics=archive_progress_values(unknown,5);
    test(metrics["speed"]==5 && metrics["remaining"]==15 && metrics["fraction"]==.25,"progress speed and remaining time use processed original bytes");
    rejected([&]{archive_create(archive_dir/"cancel-final.zip",{archive_dir/"input"},"zip",5,"",[](const ArchiveProgress &p){
      if(p.phase=="finalize")throw std::runtime_error("cancel finalization");
    });},"cancel before publishing completed archive");
    test(!fs::exists(archive_dir/"cancel-final.zip"),"cancelled finalization never publishes an archive");
    auto top=archive_dir/"top-file.zip";
    archive_create(top,{archive_dir/"input/子目录/a ; $file.txt"},"zip",5,"",{});
    auto top_rows=archive_list(top);
    test(top_rows.size()==1 && top_rows[0]["path"]=="a ; $file.txt" && top_rows[0]["regular"].get<bool>(),
         "single selected file keeps a regular filename without directory suffix");
    archive_extract(top,archive_dir/"top-out","",false,{});
    test(read(archive_dir/"top-out/a ; $file.txt")=="archive sample","single selected file extracts with original contents");
    auto gz=gzopen((archive_dir/"single.txt.gz").c_str(),"wb");require(gz,"create gzip fixture");
    gzwrite(gz,"single gzip",11);gzclose(gz);
    archive_extract(archive_dir/"single.txt.gz",archive_dir/"single-out","",false,{});
    test(read(archive_dir/"single-out/single.txt")=="single gzip","standalone compressed stream restores its filename");
    auto encrypted=archive_dir/"encrypted.zip";
    archive_create(encrypted,{archive_dir/"input"},"zip",5,"test-password",{});
    rejected([&]{archive_test(encrypted,"wrong",{});},"encrypted archive rejects wrong password");
    archive_extract(encrypted,archive_dir/"encrypted-out","test-password",false,{});
    test(read(archive_dir/"encrypted-out/input/子目录/a ; $file.txt")=="archive sample","ZIP AES-256 password roundtrip");
    rejected([&]{archive_safe_path("../escape");},"reject archive parent traversal");
    rejected([&]{archive_safe_path("/tmp/escape");},"reject absolute archive path");
    rejected([&]{archive_safe_path("C:\\escape");},"reject Windows archive path");
    fs::create_directories(archive_dir/"symlink-out");
    fs::create_directory_symlink(archive_dir/"input",archive_dir/"symlink-out/input");
    rejected([&]{archive_extract(archive_dir/"sample.zip",archive_dir/"symlink-out","",true,{});},
             "extraction never follows existing destination symlinks");
    write(archive_dir/"out-zip/input/子目录/a ; $file.txt","keep",false,false);
    archive_extract(archive_dir/"sample.zip",archive_dir/"out-zip","",false,{});
    test(read(archive_dir/"out-zip/input/子目录/a ; $file.txt")=="keep","extraction skips existing files by default");
    archive_extract(archive_dir/"sample.zip",archive_dir/"out-zip","",true,{});
    test(read(archive_dir/"out-zip/input/子目录/a ; $file.txt")=="archive sample","explicit replacement completes through a temporary file");
    rejected([&]{archive_create(archive_dir/"input/inside.zip",{archive_dir/"input"},"zip",5,"",{});},
             "reject archive output inside source folder");
    rejected([&]{archive_create(archive_dir/"cancel.zip",{archive_dir/"input"},"zip",5,"",[](const ArchiveProgress &){throw std::runtime_error("cancelled");});},"cancel archive creation");
    test(!fs::exists(archive_dir/"cancel.zip"),"cancelled creation leaves no output archive");
    auto malicious=archive_dir/"malicious.tar";
    auto aw=archive_write_new();archive_write_set_format_pax_restricted(aw);archive_write_open_filename(aw,malicious.c_str());
    for(auto name:{"innocent.txt","../escape.txt"}) {
      auto e=archive_entry_new();archive_entry_set_pathname(e,name);archive_entry_set_size(e,1);
      archive_entry_set_filetype(e,AE_IFREG);archive_entry_set_perm(e,0644);
      archive_write_header(aw,e);archive_write_data(aw,"x",1);archive_entry_free(e);
    }
    archive_write_close(aw);archive_write_free(aw);
    rejected([&]{archive_extract(malicious,archive_dir/"malicious-out","",false,{});},"preflight rejects malicious archive before any write");
    test(!fs::exists(archive_dir/"malicious-out"),"malicious archive creates no destination");
    fs::remove_all(dir);
    std::cout << checks << " native checks passed\n";
    return 0;
  } catch (const std::exception &e) {
    std::cerr << "FAIL " << e.what() << '\n';
    return 1;
  }
}
