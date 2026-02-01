/* Example JavaScript file for ESLint testing */

/**
 * Main application class
 */
class Application {
    constructor() {
        this.name = 'CID el Dill';
        this.version = '0.1.0';
    }

    /**
     * Initialize the application
     * @returns {boolean} Success status
     */
    initialize() {
        console.log(`Initializing ${this.name} v${this.version}`);
        return true;
    }

    /**
     * Get application info
     * @returns {Object} Application information
     */
    getInfo() {
        return {
            name: this.name,
            version: this.version
        };
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = Application;
}
