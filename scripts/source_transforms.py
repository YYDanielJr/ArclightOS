"""Reviewed local source adaptations. Outputs are distributed as complete DSCs."""
from pathlib import Path
import re
import subprocess
import shutil


def cryptsetup_jq_padding(tree):
    directory=tree/'tests/generators'
    library=directory/'lib.sh'
    text=library.read_text()
    assert '_jq()' not in text
    text += '''
# Read the JSON value without the metadata area's trailing binary padding.
# Backported from upstream tests/generators/lib.sh (issue 989).
_jq()
{
    local last="${!#}"
    sed 's/\\x00*$//' "$last" | jq -c "${@:1:$#-1}"
}
'''
    library.write_text(text)
    count=0
    for path in directory.glob('generate-*.sh'):
        old=path.read_text()
        new,n=re.subn(r'\bjq(?=\s+-)', '_jq', old)
        if n:
            path.write_text(new)
            count+=n
    assert count>100, count
    # Preserve the actual upstream-file change in the Debian quilt series.
    subprocess.run(['dpkg-source','--commit','.', 'astgenne-jq-padding.patch'],cwd=tree,
                   env={**__import__('os').environ,'EDITOR':'true'},check=True)
    patch=tree/'debian/patches/astgenne-jq-padding.patch'
    content=patch.read_text()
    start=content.find('--- ')
    assert start>=0
    patch.write_text('Description: Handle NUL-padded JSON in the LUKS2 test generators\n'
                     'Origin: backport, https://gitlab.com/cryptsetup/cryptsetup/-/raw/main/tests/generators/lib.sh\n'
                     'Bug: https://gitlab.com/cryptsetup/cryptsetup/-/work_items/989\n'
                     'Forwarded: not-needed\nLast-Update: 2026-10-28\n\n'+content[start:])


def linux_pc_fallback(tree):
    local=tree/'debian/config.local/amd64'
    local.mkdir(parents=True,exist_ok=True)
    (local/'defines.toml').write_text('''[[flavour]]
name = 'cloud-amd64'
enable = false

[[featureset]]
name = 'rt'
enable = false
''')
    defines=tree/'debian/config/defines.toml'
    text=defines.read_text()
    old="revision_regex = '\\d+(\\.\\d+)?(\\+deb13u\\d+)?'"
    new="revision_regex = '\\d+(\\.\\d+)?(\\+deb13u\\d+)?(\\+astgenne\\d+)?'"
    assert text.count(old)==1
    defines.write_text(text.replace(old,new))
    rules=tree/'debian/rules'
    rules.write_text(rules.read_text().replace(
        'CONTROL_FILES += debian/installer/package-list',
        'CONTROL_FILES += debian/installer/package-list $(wildcard debian/config.local/*/defines.toml)'))
    # Debian deliberately makes control-real fail after regenerating the
    # metadata. Its checksum must include the NEW source version-info too.
    # Running gencontrol.py alone leaves an old md5sum and fails at clean.
    (tree/'debian/control.md5sum').unlink(missing_ok=True)
    result=subprocess.run(['make','-f','debian/rules','debian/control-real'],cwd=tree,
                   env={**__import__('os').environ,'PYTHONPATH':'debian/lib/python','PYTHONDONTWRITEBYTECODE':'1'})
    assert result.returncode==2 and (tree/'debian/control.md5sum').is_file()
    subprocess.run(['md5sum','--check','debian/control.md5sum'],cwd=tree,check=True)
    control=(tree/'debian/control').read_text()
    assert 'Package: linux-image-6.12.113+deb13.1-amd64-unsigned\n' in control
    assert 'Package: linux-image-6.12.113+deb13.1-cloud-amd64-unsigned\n' not in control
    assert 'Package: linux-image-6.12.113+deb13.1-rt-amd64-unsigned\n' not in control


def pi_offline_installer(tree):
    # All binaries come from the complete image receipt. The installer must
    # neither refresh archive metadata nor fetch a different GRUB revision.
    settings=tree/'calamares/settings.conf'
    text=settings.read_text()
    for module in ('sources-media','sources-media-unmount','dpkg-unsafe-io','dpkg-unsafe-io-undo'):
        assert text.count('  - '+module+'\n')==1
        text=text.replace('  - '+module+'\n','')
    settings.write_text(text)
    helper=tree/'helpers/calamares-bootloader-config'
    helper.write_text('''#!/bin/bash
set -euo pipefail
mapfile -t roots < <(findmnt -rn -t proc -o TARGET | sed -n 's#^\\(/tmp/calamares-[^/]*/\\)proc$#\\1#p')
test "${#roots[@]}" -eq 1 || { echo 'Cannot identify the Calamares target root' >&2; exit 1; }
target=${roots[0]%/}
for command in grub-install grub-mkconfig grub-probe efibootmgr; do
    chroot "$target" /bin/sh -c 'command -v "$1"' sh "$command" >/dev/null
done
for platform in i386-pc x86_64-efi; do
    test -f "$target/usr/lib/grub/$platform/normal.mod"
done
if findmnt -rn -M "$target" -o SOURCE | grep -q '^/dev/mapper/luks'; then
    for package in cryptsetup-initramfs cryptsetup keyutils; do
        test "$(chroot "$target" dpkg-query -W -f='${db:Status-Status}' "$package")" = installed
    done
    printf 'UMASK=0077\\n' > "$target/etc/initramfs-tools/conf.d/initramfs-permissions"
fi
echo 'Using preinstalled source-built BIOS and UEFI GRUB components.'
''')
    packages=tree/'calamares/modules/packages.conf'
    text=packages.read_text().replace('backend: apt','backend: apt\nupdate_db: false\nupdate_system: false\nskip_if_no_internet: false')
    text=text.replace("      - 'live-task-localisation'\n",'')
    packages.write_text(text)
    final=tree/'helpers/calamares-sources-final'
    text=final.read_text().replace('http://deb.debian.org/debian-security/','https://mirrors.ustc.edu.cn/debian-security/')
    text=text.replace('http://deb.debian.org/debian/','https://mirrors.ustc.edu.cn/debian/')
    text=text.replace('http://archive.raspberrypi.com/debian/','https://archive.raspberrypi.com/debian/')
    assert text.count('exit 0\n')==1
    backports='''cat > "$CHROOT/etc/apt/sources.list.d/arclight-backports.sources" <<'BACKPORTS'
Types: deb deb-src
URIs: https://mirrors.ustc.edu.cn/debian
Suites: trixie-backports
Components: main contrib non-free non-free-firmware
Signed-By: /usr/share/keyrings/debian-archive-keyring.pgp
BACKPORTS

exit 0
'''
    text=text.replace('exit 0\n',backports)
    final.write_text(text)
    branding=tree/'calamares/branding/pios/branding.desc'
    text=branding.read_text().replace('Raspberry Pi OS','ArclightOS')
    text=re.sub(r'(?m)^(\s*shortProductName:\s*)Debian$',r'\g<1>ArclightOS',text)
    text=re.sub(r'(?m)^(\s*bootloaderEntryName:\s*)Debian$',r'\g<1>ArclightOS',text)
    branding.write_text(text)
    control=tree/'debian/control'
    text=control.read_text()
    assert 'Package: rpi-calamares-settings\n' in text
    # A package dependency makes absent boot helpers a build/assembly error.
    text=text.replace('Package: rpi-calamares-settings\n','Package: rpi-calamares-settings\n')
    lines=text.splitlines();inside=False
    for i,line in enumerate(lines):
        if line.startswith('Package: '):inside=line=='Package: rpi-calamares-settings'
        if inside and line.startswith('Depends:'):
            lines[i]=line+' grub2-common, grub-pc-bin, grub-efi-amd64-bin, efibootmgr,'
            break
    else:raise ValueError('No installer Depends field')
    control.write_text('\n'.join(lines)+'\n')
    subprocess.run(['dpkg-source','--commit','.','arclight-offline-install.patch'],cwd=tree,
                   env={**__import__('os').environ,'EDITOR':'true'},check=True)


def pixflat_render_test(tree):
    assert not (tree/'test').exists(), 'Review the restored upstream tests before replacing the stale target'
    for control in (tree/'debian/control',tree/'debian/control.in'):
        if not control.is_file():continue
        text=control.read_text()
        assert 'intltool' in text
        control.write_text(text.replace('intltool','intltool, xvfb, xauth, fonts-dejavu-core'))
    shutil.copy2(Path(__file__).parent/'build-tests/pixflat-smoke.c',tree/'debian/pixflat-smoke.c')
    rules=tree/'debian/rules'
    assert 'override_dh_auto_test:' not in rules.read_text()
    rules.write_text(rules.read_text()+'''
# The distributed source has a dangling `test` target and no test/ directory.
# Exercise the actual built engine instead of disabling all package tests.
override_dh_auto_test:
	$(CC) $(CPPFLAGS) $(CFLAGS) -o debian/pixflat-smoke debian/pixflat-smoke.c $(LDFLAGS) $$(pkg-config --cflags --libs gtk+-2.0)
	mkdir -p debian/pixflat-test-path/2.10.0/engines debian/pixflat-test-path/gtk-2.0/2.10.0/engines debian/pixflat-test-path/engines
	for dir in debian/pixflat-test-path/2.10.0/engines debian/pixflat-test-path/gtk-2.0/2.10.0/engines debian/pixflat-test-path/engines; do ln -sf $(CURDIR)/engines/pixflat/.libs/libpixflat.so $$dir/libpixflat.so; done
	GTK_PATH=$(CURDIR)/debian/pixflat-test-path GTK2_RC_FILES=/dev/null GTK_MODULES= NO_AT_BRIDGE=1 G_DEBUG=fatal-warnings xvfb-run -a ./debian/pixflat-smoke
''')


def gtk3_pixbuf_scale(tree):
    path=tree/'gtk/gtkcellrendererpixbuf.c'
    text=path.read_text()
    # The Pi property must obey the same explicit-notification contract as
    # upstream integer GTK properties. Zero is not a valid pixbuf scale.
    old='''P_("The scale of the pixbuf"),
						      0,
						      G_MAXUINT,
						      1,
						      GTK_PARAM_READWRITE)'''
    if old not in text:
        match=re.search(r'(P_\("The scale of the pixbuf"\),\s*)0,(\s*G_MAXUINT,\s*1,\s*)GTK_PARAM_READWRITE',text)
        assert match
        text=text[:match.start()]+match[1]+'1,'+match[2]+'(GTK_PARAM_READWRITE | G_PARAM_EXPLICIT_NOTIFY)'+text[match.end():]
    else:
        text=text.replace(old,old.replace('      0,','      1,').replace('GTK_PARAM_READWRITE)','(GTK_PARAM_READWRITE | G_PARAM_EXPLICIT_NOTIFY))'))
    old='''    case PROP_SCALE:
      priv->scale = g_value_get_uint (value);
      if (priv->image_def)
      {
        GdkPixbuf *pixbuf = gtk_image_definition_get_pixbuf (priv->image_def);
        take_image_definition (cellpixbuf, gtk_image_definition_new_pixbuf (pixbuf, priv->scale));
      }
      break;'''
    new='''    case PROP_SCALE:
      if (priv->scale == g_value_get_uint (value))
        break;
      priv->scale = g_value_get_uint (value);
      if (gtk_image_definition_get_storage_type (priv->image_def) == GTK_IMAGE_PIXBUF)
        {
          GdkPixbuf *pixbuf = gtk_image_definition_get_pixbuf (priv->image_def);
          take_image_definition (cellpixbuf, gtk_image_definition_new_pixbuf (pixbuf, priv->scale));
        }
      g_object_notify_by_pspec (object, pspec);
      break;'''
    assert text.count(old)==1
    path.write_text(text.replace(old,new))
    path=tree/'testsuite/gtk/notify.c';text=path.read_text()
    pos=text.index('int\nmain (')
    text=text[:pos]+'''static void
test_pixbuf_scale_storage (void)
{
  GtkCellRenderer *renderer = gtk_cell_renderer_pixbuf_new ();
  GIcon *icon = g_themed_icon_new ("folder");
  GIcon *actual = NULL;
  gchar *name = NULL;
  GdkPixbuf *pixbuf = gdk_pixbuf_new (GDK_COLORSPACE_RGB, TRUE, 8, 16, 16);
  GdkPixbuf *actual_pixbuf = NULL;
  g_object_ref_sink (renderer);
  g_object_set (renderer, "icon-name", "folder", "scale", 2, NULL);
  g_object_get (renderer, "icon-name", &name, NULL);
  g_assert_cmpstr (name, ==, "folder");
  g_free (name);
  g_object_set (renderer, "gicon", icon, "scale", 3, NULL);
  g_object_get (renderer, "gicon", &actual, NULL);
  g_assert_true (g_icon_equal (icon, actual));
  g_clear_object (&actual);
  g_object_set (renderer, "pixbuf", pixbuf, "scale", 2, NULL);
  g_object_get (renderer, "pixbuf", &actual_pixbuf, NULL);
  g_assert_true (actual_pixbuf == pixbuf);
  g_clear_object (&actual_pixbuf);
  g_object_unref (pixbuf);
  g_object_unref (icon);
  g_object_unref (renderer);
}

'''+text[pos:]
    assert text.count('result = g_test_run ();')==1
    text=text.replace('result = g_test_run ();','g_test_add_func ("/Astgenne/PixbufScaleStorage", test_pixbuf_scale_storage);\n\n  result = g_test_run ();')
    path.write_text(text)
    subprocess.run(['dpkg-source','--commit','.','astgenne-pixbuf-scale.patch'],cwd=tree,
                   env={**__import__('os').environ,'EDITOR':'true'},check=True)


def linux_local_wrapper(tree):
    # Debian gives a new source revision a distinct ABI serial. Keep that
    # separation so archive modules cannot be confused with our rebuilt ones.
    old_abi='6.12.113+deb13';new_abi='6.12.113+deb13.1'
    for path in sorted((tree/'debian').rglob('*')):
        if not path.is_file() or 'signatures' in path.parts:continue
        try:text=path.read_text()
        except UnicodeDecodeError:continue
        if old_abi in text:path.write_text(text.replace(old_abi,new_abi))
        if old_abi in path.name:path.rename(path.with_name(path.name.replace(old_abi,new_abi)))
    old='6.12.113-1';new='6.12.113-1+astgenne1'
    for name in ('control','rules.real','rules.gen'):
        path=tree/'debian'/name
        path.write_text(path.read_text().replace(old,new))
    control=tree/'debian/control'
    blocks=control.read_text().strip().split('\n\n')
    source=blocks[0].splitlines()
    source=[line for line in source if not line.startswith('Uploaders:')]
    for i,line in enumerate(source):
        if line.startswith('Maintainer:'):
            source[i]='Maintainer: YYDaniel <yydaniel@localhost>'
        if line.startswith('Build-Depends-Arch:'):
            source[i]='Build-Depends-Arch: '+', '.join(x.strip() for x in line.split(':',1)[1].split(',')
                if 'cloud-amd64' not in x and '-rt-amd64' not in x)
    selected=['\n'.join(source)]
    names=('linux-headers-amd64','linux-image-amd64','linux-image-6.12.113+deb13.1-amd64')
    for block in blocks[1:]:
        if block.splitlines()[0] not in ['Package: '+x for x in names]:continue
        block=block.replace('(signed)','(Astgenne source rebuild, unsigned)')
        block=block.replace('The kernel image is signed for use with Secure Boot.',
                            'The kernel image is locally compiled. Secure Boot requires local signing.')
        selected.append(block)
    assert len(selected)==4
    control.write_text('\n\n'.join(selected)+'\n')
    path=tree/'debian/rules.gen';output=[];skip=False
    markers=('_cloud-amd64','_rt','_installer')
    for line in path.read_text().splitlines():
        if re.match(r'^(?:build|binary)-[^ :]*:',line):
            target,deps=line.split(':',1)
            skip=any(x in target for x in markers)
            if not skip:output.append(target+':'+ ' '.join(x for x in deps.split() if not any(m in x for m in markers)))
        elif not skip:
            output.append(line)
    path.write_text('\n'.join(output)+'\n')
    path=tree/'debian/rules.real';text=path.read_text()
    attach='\tsbattach --attach $(SIGNATURE_DIR)/boot/vmlinuz-$(REAL_VERSION).sig \\\n\t\t$(INSTALL_DIR)/boot/vmlinuz-$(REAL_VERSION)\n'
    assert text.count(attach)==1
    path.write_text(text.replace(attach,'\t# Local source-built fallback: no Debian vendor signature is attached.\n'))
    (tree/'debian/README.Astgenne').write_text(
        'This local revision packages the locally built ordinary amd64 kernel.\n'
        'It does not attach the signatures supplied for Debian archive binaries.\n'
        'The executable and modules must pass the build-origin payload audit.\n'
        'Secure Boot requires the owner\'s signing key and firmware enrollment.\n')
