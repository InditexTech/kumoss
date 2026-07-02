import cn from "classnames";
import {useEffect, useRef} from "react";
import Lottie from "lottie-react";
import type {LottieRefCurrentProps} from "lottie-react";
import animations from "./animations";
import styles from './AssistantAnimatedIcon.module.css';

export interface AssistantAnimatedIconProps {
    autoplay?: boolean;
    className?: string;
    height?: number;
    isPaused?: boolean;
    isStopped?: boolean;
    loop?: boolean;
    phase: "icon" | "listening" | "speaking" | "loading" | "standby" | "error";
    speed?: number;
    theme: "blue" | "white";
    width?: number;
}

export const AssistantAnimatedIcon = ({
                                          autoplay = true,
                                          className = "",
                                          height = 30,
                                          isPaused = false,
                                          isStopped = false,
                                          loop = true,
                                          phase = "icon",
                                          speed = 1,
                                          theme = "blue",
                                          width = 30,
                                      }: AssistantAnimatedIconProps) => {
    const lottieRef = useRef<LottieRefCurrentProps>(null);
    const currentAnimation = animations[theme][phase];

    useEffect(() => {
        if (lottieRef.current) {
            lottieRef.current.setSpeed(speed);
        }
    }, [speed]);

    useEffect(() => {
        if (!lottieRef.current) return;
        if (isStopped) {
            lottieRef.current.stop();
        } else if (isPaused) {
            lottieRef.current.pause();
        } else {
            lottieRef.current.play();
        }
    }, [isStopped, isPaused]);

    return (
        <div
            className={cn(styles.assistantAnimatedIcon, className)}
        >
            <Lottie
                lottieRef={lottieRef}
                animationData={currentAnimation}
                loop={loop}
                autoplay={autoplay}
                style={{width, height}}
            />
        </div>
    );
};
