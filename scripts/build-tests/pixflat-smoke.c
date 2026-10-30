/* SPDX-License-Identifier: MIT
 * Load the just-built GTK2 engine and render representative controls in Xvfb.
 */
#include <gtk/gtk.h>
#include <string.h>

int main(int argc, char **argv)
{
    gtk_init(&argc, &argv);
    gtk_rc_parse_string("style \"astgenne-probe\" { engine \"pixflat\" {} }\n"
                        "widget_class \"*\" style \"astgenne-probe\"\n");
    GtkWidget *window = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_default_size(GTK_WINDOW(window), 400, 320);
    GtkWidget *box = gtk_vbox_new(FALSE, 8);
    gtk_container_set_border_width(GTK_CONTAINER(box), 12);
    gtk_container_add(GTK_CONTAINER(window), box);
    GtkWidget *button = gtk_button_new_with_label("PiXflat render probe");
    GtkWidget *entry = gtk_entry_new();
    gtk_entry_set_text(GTK_ENTRY(entry), "Source-built GTK2 theme");
    GtkWidget *check = gtk_check_button_new_with_label("Enabled option");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(check), TRUE);
    GtkWidget *progress = gtk_progress_bar_new();
    gtk_progress_bar_set_fraction(GTK_PROGRESS_BAR(progress), 0.55);
    GtkWidget *scale = gtk_hscale_new_with_range(0, 100, 1);
    gtk_range_set_value(GTK_RANGE(scale), 45);
    GtkWidget *widgets[] = { button, entry, check, progress, scale };
    for (guint i = 0; i < G_N_ELEMENTS(widgets); ++i)
        gtk_box_pack_start(GTK_BOX(box), widgets[i], FALSE, FALSE, 0);
    gtk_widget_show_all(window);
    for (int i = 0; i < 50; ++i) {
        while (gtk_events_pending()) gtk_main_iteration();
        g_usleep(10000);
    }
    GtkStyle *style = gtk_widget_get_style(button);
    if (strcmp(G_OBJECT_TYPE_NAME(style), "PixflatStyle") != 0) {
        g_printerr("Wrong theme engine: %s\n", G_OBJECT_TYPE_NAME(style));
        return 1;
    }
    GtkAllocation allocation;
    gtk_widget_get_allocation(window, &allocation);
    GdkPixbuf *image = gdk_pixbuf_get_from_drawable(NULL, gtk_widget_get_window(window),
        gtk_widget_get_colormap(window), 0, 0, 0, 0, allocation.width, allocation.height);
    if (!image) return 2;
    const guchar *pixels = gdk_pixbuf_get_pixels(image);
    int channels = gdk_pixbuf_get_n_channels(image);
    int stride = gdk_pixbuf_get_rowstride(image);
    guint changed = 0;
    for (int y = 0; y < gdk_pixbuf_get_height(image); ++y)
        for (int x = 0; x < gdk_pixbuf_get_width(image); ++x)
            if (memcmp(pixels, pixels + y * stride + x * channels, 3)) ++changed;
    g_print("PixflatStyle loaded; rendered %dx%d; nonuniform pixels: %u\n",
            allocation.width, allocation.height, changed);
    g_object_unref(image);
    gtk_widget_destroy(window);
    while (gtk_events_pending()) gtk_main_iteration();
    return changed > 100 ? 0 : 3;
}
