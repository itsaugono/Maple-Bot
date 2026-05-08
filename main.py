from templates import TemplateManager
from ui import MapleStoryUI


def main():
    template_mgr = TemplateManager()
    template_mgr.load_config()
    app = MapleStoryUI(template_mgr)
    app.setup()
    app.run()


if __name__ == "__main__":
    main()
