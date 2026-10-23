```javascript
"use strict";

document.addEventListener("DOMContentLoaded", function () {
    const grievanceForm = document.getElementById("grievanceForm");
    const formMessage = document.getElementById("formMessage");

    const trackingForm = document.getElementById("trackingForm");
    const trackingMessage = document.getElementById("trackingMessage");
    const trackingResult = document.getElementById("trackingResult");

    // Display messages safely
    function showMessage(element, message, type) {
        if (!element) return;

        element.textContent = message;
        element.className = type === "success"
            ? "success-message"
            : "error-message";

        element.hidden = false;
    }

    // Submit a new grievance
    if (grievanceForm) {
        grievanceForm.addEventListener("submit", async function (event) {
            event.preventDefault();

            const submitButton = grievanceForm.querySelector(
                'button[type="submit"]'
            );

            if (submitButton) {
                submitButton.disabled = true;
                submitButton.textContent = "Submitting...";
            }

            if (formMessage) {
                formMessage.hidden = true;
                formMessage.textContent = "";
            }

            const formData = new FormData(grievanceForm);

            const payload = {
                citizenName: String(formData.get("citizenName") || "").trim(),
                category: String(formData.get("category") || "").trim(),
                location: String(formData.get("location") || "").trim(),
                description: String(formData.get("description") || "").trim()
            };

            try {
                const response = await fetch("/api/grievances", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "Accept": "application/json"
                    },
                    body: JSON.stringify(payload),
                    cache: "no-store"
                });

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.error || data.message ||
                        "Unable to submit the grievance."
                    );
                }

                showMessage(
                    formMessage,
                    "Grievance submitted successfully! Reference number: " +
                    data.reference,
                    "success"
                );

                // Put the new reference into the tracking form
                if (trackingForm && data.reference) {
                    const referenceInput =
                        trackingForm.elements.namedItem("referenceNumber");

                    if (referenceInput) {
                        referenceInput.value = data.reference;
                    }
                }

                grievanceForm.reset();

                // Keep the reference available after resetting the form
                if (trackingForm && data.reference) {
                    const referenceInput =
                        trackingForm.elements.namedItem("referenceNumber");

                    if (referenceInput) {
                        referenceInput.value = data.reference;
                    }
                }

            } catch (error) {
                console.error("Grievance submission error:", error);

                showMessage(
                    formMessage,
                    error.message || "Something went wrong. Please try again.",
                    "error"
                );
            } finally {
                if (submitButton) {
                    submitButton.disabled = false;
                    submitButton.textContent = "Submit Grievance";
                }
            }
        });
    }

    // Track a grievance using its reference number
    if (trackingForm) {
        trackingForm.addEventListener("submit", async function (event) {
            event.preventDefault();

            const referenceInput =
                trackingForm.elements.namedItem("referenceNumber");

            const reference = referenceInput
                ? referenceInput.value.trim()
                : "";

            if (!reference) {
                showMessage(
                    trackingMessage,
                    "Please enter your grievance reference number.",
                    "error"
                );
                return;
            }

            const trackButton = trackingForm.querySelector(
                'button[type="submit"]'
            );

            if (trackButton) {
                trackButton.disabled = true;
                trackButton.textContent = "Checking...";
            }

            if (trackingMessage) {
                trackingMessage.hidden = true;
                trackingMessage.textContent = "";
            }

            if (trackingResult) {
                trackingResult.hidden = true;
            }

            try {
                const response = await fetch(
                    "/api/grievances/" + encodeURIComponent(reference),
                    {
                        method: "GET",
                        headers: {
                            "Accept": "application/json"
                        },
                        cache: "no-store"
                    }
                );

                const data = await response.json();

                if (!response.ok) {
                    throw new Error(
                        data.error || data.message ||
                        "Grievance not found. Check your reference number."
                    );
                }

                displayTrackingResult(data);

            } catch (error) {
                console.error("Grievance tracking error:", error);

                showMessage(
                    trackingMessage,
                    error.message || "Unable to track the grievance.",
                    "error"
                );
            } finally {
                if (trackButton) {
                    trackButton.disabled = false;
                    trackButton.textContent = "Track Grievance";
                }
            }
        });
    }

    // Display the grievance information returned by Flask
    function displayTrackingResult(data) {
        const referenceElement =
            document.getElementById("resultReference");

        const categoryElement =
            document.getElementById("resultCategory");

        const locationElement =
            document.getElementById("resultLocation");

        const statusElement =
            document.getElementById("resultStatus");

        if (referenceElement) {
            referenceElement.textContent =
                data.reference || data.reference_number || "—";
        }

        if (categoryElement) {
            categoryElement.textContent = data.category || "—";
        }

        if (locationElement) {
            locationElement.textContent = data.location || "—";
        }

        if (statusElement) {
            statusElement.textContent = data.status || "—";
        }

        if (trackingResult) {
            trackingResult.hidden = false;
        }

        showMessage(
            trackingMessage,
            "Grievance details retrieved successfully.",
            "success"
        );
    }
});
```