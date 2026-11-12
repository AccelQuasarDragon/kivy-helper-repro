from kivy.app import App
from kivy.uix.label import Label


class ReproApp(App):
    def build(self):
        return Label(text='kivy-helper-repro')


if __name__ == '__main__':
    ReproApp().run()
