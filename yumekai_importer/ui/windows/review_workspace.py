from PySide6.QtWidgets import QTabWidget, QVBoxLayout, QWidget


class ReviewWorkspace(QWidget):
    def __init__(self, pending, store):
        super().__init__()
        self.pending, self.store = pending, store
        self.tabs = QTabWidget()
        self.tabs.setObjectName('reviewTabs')
        self.tabs.addTab(pending, 'Preparar fichas')
        self.tabs.addTab(store, 'En tienda')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 0)
        layout.addWidget(self.tabs)

    def open_page(self, page):
        self.tabs.setCurrentWidget(page)

    def can_leave(self):
        return self.pending.can_leave() and self.store.can_leave()
