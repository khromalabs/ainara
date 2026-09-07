class ToolsHelloComponent {
    constructor() {
        this.titleEl = document.getElementById('hello-title');
        this.messageEl = document.getElementById('hello-message');
        this.timestampEl = document.getElementById('hello-timestamp');
    }

    render(data) {
        if (!data) {
            console.error('No data received for ToolsHello component');
            return;
        }

        this.titleEl.textContent = 'Hello Component';
        this.messageEl.textContent = data.message || 'No message provided';
        this.timestampEl.textContent = `Timestamp: ${data.timestamp || 'N/A'}`;
    }
}

const component = new ToolsHelloComponent();

function handleData(skillData) {
    console.log("ToolsHello component handleData received:", skillData);
    component.render(skillData);
}

window.addEventListener('message', (event) => {
    // A basic security check to accept messages only from the parent window
    if (event.source !== window.parent) {
        return;
    }
    handleData(event.data);
});
